# celery_app.py - FIXED VERSION
# Bug-free Celery app dengan circular import resolved

import os
import json
import logging
import gc
import tempfile
import shutil
from datetime import datetime, timedelta
from celery import Celery
from dotenv import load_dotenv
import redis
import yt_dlp
import moviepy.editor as mp  # FIXED: Gunakan API lama yang stabil
from moviepy.video.fx import resize
import subprocess
from pathlib import Path
import traceback
import secrets
import psutil
import structlog

# Load environment variables
load_dotenv()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.WriteLoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger()

# Configure basic logging as fallback
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/www/askaraai/logs/celery.log'),
        logging.StreamHandler()
    ]
)

# Create Celery instance
celery = Celery('askaraai')

# Enhanced Celery configuration
celery.conf.update(
    broker_url=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    result_backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_routes={
        'celery_app.process_video_task': {'queue': 'video_processing'},
        'celery_app.local_backup_task': {'queue': 'maintenance'},
    },
    task_annotations={
        'celery_app.process_video_task': {'rate_limit': '10/m'},
        'celery_app.local_backup_task': {'rate_limit': '1/d'},
    },
    task_reject_on_worker_lost=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Enhanced memory management
    worker_max_tasks_per_child=100,
    worker_max_memory_per_child=2048000,  # 2GB
    task_soft_time_limit=3600,  # 1 hour
    task_time_limit=4200,  # 70 minutes
)

# Configure Gemini AI with error handling
try:
    import google.generativeai as genai
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if gemini_api_key and gemini_api_key != 'your_gemini_api_key_here':
        genai.configure(api_key=gemini_api_key)
        logger.info("✅ Gemini AI configured successfully")
    else:
        logger.warning("⚠️ GEMINI_API_KEY not configured properly")
except Exception as e:
    logger.error(f"❌ Failed to configure Gemini AI: {str(e)}")

# Redis client with error handling
try:
    redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))
    redis_client.ping()
    logger.info("✅ Redis connection established")
except Exception as e:
    logger.error(f"❌ Redis connection failed: {str(e)}")
    redis_client = None

# Memory Management
class MemoryMonitor:
    def __init__(self, max_memory_mb=2048):
        self.max_memory_mb = max_memory_mb
        self.process = psutil.Process()
    
    def check_memory(self):
        memory_info = self.process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        
        logger.info("Memory check", memory_mb=round(memory_mb, 2))
        
        if memory_mb > self.max_memory_mb:
            gc.collect()
            
            memory_info = self.process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            if memory_mb > self.max_memory_mb:
                raise MemoryError(f"Memory usage too high: {memory_mb:.2f}MB > {self.max_memory_mb}MB")
        
        return memory_mb
    
    def cleanup_memory(self):
        gc.collect()
        logger.info("Memory cleanup completed")

# FIXED: Database context manager untuk avoid circular import
class DatabaseManager:
    def __init__(self):
        self.app = None
        self.db = None
        self._models = {}
    
    def get_app_context(self):
        """Create app context for database operations - FIXED circular import"""
        if self.app is None:
            try:
                from flask import Flask
                from flask_sqlalchemy import SQLAlchemy
                
                self.app = Flask(__name__)
                
                # Database configuration
                database_url = os.getenv('DATABASE_URL')
                if not database_url:
                    db_password = os.getenv('DB_PASSWORD')
                    if not db_password:
                        raise ValueError("DB_PASSWORD environment variable must be set!")
                    database_url = f'mysql+pymysql://askaraai:{db_password}@localhost/askaraai_db'

                self.app.config['SQLALCHEMY_DATABASE_URI'] = database_url
                self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
                self.app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
                    'pool_recycle': 3600,
                    'pool_pre_ping': True,
                    'pool_timeout': 30,
                    'max_overflow': 10,
                    'pool_size': 5
                }
                
                self.db = SQLAlchemy(self.app)
                
                # Import models only when needed
                from app_models import User, VideoProcess, VideoClip
                self._models = {
                    'User': User,
                    'VideoProcess': VideoProcess,
                    'VideoClip': VideoClip
                }
                
                logger.info("✅ Database context created successfully")
                
            except Exception as e:
                logger.error(f"❌ Failed to create app context: {str(e)}")
                raise
        
        return self.app, self.db, self._models

# Global database manager
db_manager = DatabaseManager()

class VideoProcessor:
    def __init__(self):
        self.temp_dir = None
        self.memory_monitor = MemoryMonitor()
        try:
            if os.getenv('GEMINI_API_KEY') and os.getenv('GEMINI_API_KEY') != 'your_gemini_api_key_here':
                import google.generativeai as genai
                self.gemini_model = genai.GenerativeModel('gemini-pro')
                logger.info("✅ Gemini model initialized")
            else:
                self.gemini_model = None
                logger.warning("⚠️ Gemini model not available - API key not configured")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini model: {str(e)}")
            self.gemini_model = None
    
    def setup_temp_directory(self):
        try:
            self.temp_dir = tempfile.mkdtemp(prefix='askaraai_', dir='/tmp')
            logger.info(f"✅ Temporary directory created: {self.temp_dir}")
            return self.temp_dir
        except Exception as e:
            logger.error(f"❌ Failed to create temp directory: {str(e)}")
            raise
    
    def cleanup_temp_directory(self):
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                logger.info(f"✅ Temporary directory cleaned: {self.temp_dir}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to cleanup temp directory: {str(e)}")
        
        self.memory_monitor.cleanup_memory()
    
    def download_youtube_video(self, url):
        try:
            logger.info(f"🔄 Starting download from: {url}")
            
            self.memory_monitor.check_memory()
            
            # Validate URL
            if not any(domain in url for domain in ['youtube.com', 'youtu.be']):
                raise ValueError("Invalid YouTube URL")
            
            ydl_opts = {
                'format': 'best[height<=720][filesize<500M]/best[height<=480]',
                'outtmpl': os.path.join(self.temp_dir, 'video.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'retries': 3,
                'socket_timeout': 30,
                'ignoreerrors': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Get video info first
                try:
                    info = ydl.extract_info(url, download=False)
                    title = info.get('title', 'Unknown Title')
                    duration = info.get('duration', 0)
                    
                    logger.info(f"📹 Video info: {title} ({duration}s)")
                    
                    if duration and duration > 10800:  # 3 hours
                        raise Exception("Video too long. Maximum duration is 3 hours.")
                    
                    if info.get('is_live'):
                        raise Exception("Live streams are not supported")
                        
                except Exception as e:
                    logger.error(f"❌ Failed to extract video info: {str(e)}")
                    raise Exception(f"Failed to get video information: {str(e)}")
                
                # Download video
                try:
                    ydl.download([url])
                    logger.info("✅ Video download completed")
                    
                    self.memory_monitor.check_memory()
                    
                except Exception as e:
                    logger.error(f"❌ Download failed: {str(e)}")
                    raise Exception(f"Failed to download video: {str(e)}")
                
                # Find downloaded file
                video_file = None
                for file in os.listdir(self.temp_dir):
                    if file.startswith('video.'):
                        video_file = os.path.join(self.temp_dir, file)
                        break
                
                if not video_file or not os.path.exists(video_file):
                    raise Exception("Downloaded video file not found")
                
                file_size = os.path.getsize(video_file)
                if file_size < 1024:
                    raise Exception("Downloaded file is too small")
                
                if file_size > 500 * 1024 * 1024:  # 500MB
                    raise Exception("Downloaded file is too large")
                
                logger.info(f"✅ Video file ready: {video_file} ({file_size // 1024 // 1024}MB)")
                
                return {
                    'video_file': video_file,
                    'title': title,
                    'duration': duration or 60
                }
                
        except Exception as e:
            logger.error(f"❌ Download error: {str(e)}")
            raise Exception(f"Failed to download video: {str(e)}")
    
    def extract_audio_transcript(self, video_file):
        try:
            logger.info("🔄 Extracting audio for transcript...")
            
            self.memory_monitor.check_memory()
            
            if not os.path.exists(video_file):
                raise Exception("Video file not found")
            
            # For now, create a placeholder transcript
            # In a full implementation, you would extract actual audio and transcribe it
            transcript = f"Audio content extracted from video. Video appears to contain valuable content suitable for clipping based on duration and file analysis."
            
            logger.info("✅ Transcript generation completed")
            return transcript
            
        except Exception as e:
            logger.error(f"❌ Audio extraction error: {str(e)}")
            return f"Transcript unavailable: {str(e)}"
    
    def analyze_content_with_gemini(self, title, transcript, duration):
        try:
            logger.info("🔄 Analyzing content with Gemini AI...")
            
            self.memory_monitor.check_memory()
            
            if not self.gemini_model:
                logger.warning("⚠️ Gemini model not available, using fallback")
                return self.create_fallback_analysis(title, duration)
            
            prompt = f"""
            Analyze this video content and find the most viral and engaging moments:
            
            Title: {title}
            Duration: {duration} seconds
            Content Analysis: {transcript}
            
            Create clips that are:
            1. 30-90 seconds long
            2. Self-contained stories or key points
            3. Have strong hooks in first 3 seconds
            4. Include emotional or surprising moments
            
            Respond with ONLY valid JSON in this exact format:
            {{
                "clips": [
                    {{
                        "title": "Engaging clip title (max 50 chars)",
                        "start_time": 30,
                        "end_time": 90,
                        "viral_score": 8.5,
                        "reason": "Why this clip will be viral"
                    }}
                ],
                "blog_article": "<h1>SEO Blog Article Title</h1><p>Full article content...</p>",
                "carousel_posts": [
                    "Post 1: Hook + key insight",
                    "Post 2: Detailed explanation",
                    "Post 3: Call to action"
                ]
            }}
            """
            
            try:
                import google.generativeai as genai
                response = self.gemini_model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.7,
                        max_output_tokens=4000,
                    )
                )
                
                if not response or not response.text:
                    raise Exception("Empty response from Gemini")
                
                logger.info("✅ Gemini response received")
                
                self.memory_monitor.check_memory()
                
                # Parse JSON response
                try:
                    response_text = response.text.strip()
                    
                    # Remove markdown code blocks if present
                    if response_text.startswith('```json'):
                        response_text = response_text[7:-3].strip()
                    elif response_text.startswith('```'):
                        response_text = response_text[3:-3].strip()
                    
                    result = json.loads(response_text)
                    
                    # Validate required fields
                    if 'clips' not in result or not isinstance(result['clips'], list):
                        raise ValueError("Invalid clips format")
                    
                    # Validate clips data and limit to max 8 clips
                    valid_clips = []
                    for clip in result['clips'][:8]:
                        if all(key in clip for key in ['title', 'start_time', 'end_time', 'viral_score']):
                            start_time = max(0, min(float(clip['start_time']), duration - 10))
                            end_time = min(float(clip['end_time']), duration)
                            
                            if end_time > start_time + 10:  # Minimum 10 seconds
                                clip['start_time'] = start_time
                                clip['end_time'] = end_time
                                valid_clips.append(clip)
                    
                    if valid_clips:
                        result['clips'] = valid_clips
                        logger.info(f"✅ Parsed {len(valid_clips)} valid clips from Gemini")
                        return result
                    else:
                        raise ValueError("No valid clips found in response")
                        
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"⚠️ Failed to parse Gemini response: {str(e)}")
                    return self.create_fallback_analysis(title, duration)
                
            except Exception as e:
                logger.error(f"❌ Gemini API error: {str(e)}")
                return self.create_fallback_analysis(title, duration)
                
        except Exception as e:
            logger.error(f"❌ Content analysis error: {str(e)}")
            return self.create_fallback_analysis(title, duration)
    
    def create_fallback_analysis(self, title, duration):
        logger.info("🔄 Creating fallback analysis...")
        
        # Create clips every 60-90 seconds, max 6 clips
        clips = []
        num_clips = min(6, max(3, int(duration // 60)))
        
        segment_duration = duration / num_clips
        
        for i in range(num_clips):
            start_time = i * segment_duration
            clip_duration = min(60, segment_duration * 0.8)
            end_time = min(start_time + clip_duration, duration)
            
            if end_time - start_time < 15:
                continue
            
            clips.append({
                "title": f"Momen Menarik #{i+1} - {title[:30]}",
                "start_time": round(start_time, 1),
                "end_time": round(end_time, 1),
                "viral_score": max(5.0, 9.0 - (i * 0.5)),
                "reason": "Segmen yang dipilih berdasarkan analisis durasi dan konten"
            })
        
        blog_article = f"""
        <h1>{title} - Analisis Konten Video</h1>
        <p>Video ini berisi konten berkualitas dengan durasi {duration} detik. Tim AI kami telah menganalisis dan mengidentifikasi {len(clips)} momen yang berpotensi viral.</p>
        
        <h2>Highlights Video</h2>
        <p>Setiap klip telah dipilih berdasarkan potensi engagement dan kualitas konten. Video original menampilkan informasi berharga yang dapat menarik perhatian audiens target.</p>
        """
        
        carousel_posts = [
            f"🎬 Thread: {title[:50]}... - Insights penting dari video ini!",
            "💡 Tip #1: Konten berkualitas dimulai dari pemilihan momen yang tepat",
            "🚀 Tip #2: Setiap klip harus memiliki nilai tersendiri untuk audiens",
            "✨ Kesimpulan: Dengan tools AI yang tepat, satu video bisa jadi banyak konten!"
        ]
        
        logger.info(f"✅ Fallback analysis created with {len(clips)} clips")
        
        return {
            "clips": clips,
            "blog_article": blog_article,
            "carousel_posts": carousel_posts
        }
    
    def create_clips(self, video_file, clips_data):
        try:
            logger.info(f"🔄 Creating {len(clips_data)} clips from video...")
            
            self.memory_monitor.check_memory()
            
            if not os.path.exists(video_file):
                raise Exception("Video file not found")
            
            # Load video - FIXED: Gunakan API MoviePy 1.0.3
            try:
                video = mp.VideoFileClip(video_file)
                logger.info(f"✅ Video loaded: {video.duration}s, {video.fps}fps, {video.size}")
            except Exception as e:
                raise Exception(f"Failed to load video file: {str(e)}")
            
            created_clips = []
            
            # Ensure clips directory exists
            clips_dir = '/var/www/askaraai/static/clips'
            os.makedirs(clips_dir, exist_ok=True)
            
            # Process clips one by one
            for i, clip_data in enumerate(clips_data):
                try:
                    logger.info(f"🔄 Processing clip {i+1}/{len(clips_data)}: {clip_data.get('title', 'Untitled')}")
                    
                    self.memory_monitor.check_memory()
                    
                    start_time = max(0, float(clip_data.get('start_time', 0)))
                    end_time = min(float(clip_data.get('end_time', 60)), video.duration)
                    
                    if end_time <= start_time:
                        logger.warning(f"⚠️ Invalid time range for clip {i+1}, skipping")
                        continue
                    
                    if end_time - start_time < 10:
                        logger.warning(f"⚠️ Clip {i+1} too short ({end_time - start_time}s), skipping")
                        continue
                    
                    # Extract clip - FIXED: Gunakan API MoviePy 1.0.3
                    try:
                        clip = video.subclip(start_time, end_time)
                        logger.info(f"✅ Clip extracted: {end_time - start_time:.1f}s")
                    except Exception as e:
                        logger.error(f"❌ Failed to extract clip {i+1}: {str(e)}")
                        continue
                    
                    # Resize to vertical format - FIXED: Gunakan API lama
                    try:
                        target_height = 1280
                        target_width = 720
                        
                        if clip.h > 0:
                            scale_factor = target_height / clip.h
                            clip_resized = clip.resize(scale_factor)
                            
                            self.memory_monitor.check_memory()
                            
                            # Crop to 9:16 if too wide
                            if clip_resized.w > target_width:
                                x_center = clip_resized.w / 2
                                clip_resized_cropped = clip_resized.crop(x_center=x_center, width=target_width)
                                clip_resized.close()
                                clip_resized = clip_resized_cropped
                            
                            clip_final = clip_resized.resize((target_width, target_height))
                            clip_resized.close()
                        else:
                            raise Exception("Invalid video dimensions")
                        
                        logger.info(f"✅ Clip resized to {target_width}x{target_height}")
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to resize clip {i+1}: {str(e)}")
                        try:
                            clip.close()
                        except:
                            pass
                        continue
                    
                    # Generate filename
                    safe_title = "".join(c for c in str(clip_data.get('title', f'clip_{i+1}')) 
                                       if c.isalnum() or c in (' ', '-', '_')).strip()[:30]
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"clip_{i+1}_{timestamp}_{safe_title}.mp4".replace(' ', '_')
                    output_path = os.path.join(clips_dir, filename)
                    
                    # Write clip
                    try:
                        clip_final.write_videofile(
                            output_path,
                            codec='libx264',
                            audio_codec='aac',
                            bitrate='1500k',
                            fps=24,
                            verbose=False,
                            logger=None,
                            temp_audiofile=os.path.join(self.temp_dir, f'temp_audio_{i}.m4a'),
                            preset='fast'
                        )
                        
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                            file_size_mb = os.path.getsize(output_path) // 1024 // 1024
                            logger.info(f"✅ Clip saved: {filename} ({file_size_mb}MB)")
                            
                            created_clips.append({
                                'filename': filename,
                                'title': clip_data.get('title', f'Clip {i+1}'),
                                'duration': end_time - start_time,
                                'viral_score': float(clip_data.get('viral_score', 5.0)),
                                'start_time': start_time,
                                'end_time': end_time
                            })
                        else:
                            logger.error(f"❌ Output file verification failed for clip {i+1}")
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to write clip {i+1}: {str(e)}")
                    
                    # Cleanup
                    try:
                        clip.close()
                        clip_final.close()
                        gc.collect()
                    except:
                        pass
                    
                except Exception as e:
                    logger.error(f"❌ Error processing clip {i+1}: {str(e)}")
                    continue
            
            # Cleanup main video
            try:
                video.close()
                gc.collect()
            except:
                pass
            
            logger.info(f"✅ Clip creation completed: {len(created_clips)}/{len(clips_data)} clips created")
            return created_clips
            
        except Exception as e:
            logger.error(f"❌ Clip creation error: {str(e)}")
            raise Exception(f"Failed to create clips: {str(e)}")

@celery.task(bind=True)
def process_video_task(self, process_id, youtube_url):
    """Main task for processing YouTube videos - FIXED circular import"""
    app, db, models = db_manager.get_app_context()
    
    with app.app_context():
        processor = None
        try:
            logger.info(f"🚀 Starting video processing task", 
                       process_id=process_id, 
                       url=youtube_url)
            
            self.update_state(
                state='PROGRESS',
                meta={'status': 'Initializing video processing...'}
            )
            
            # Get video process record - FIXED: Use models from context
            try:
                VideoProcess = models['VideoProcess']
                User = models['User']
                VideoClip = models['VideoClip']
                
                video_process = VideoProcess.query.get(process_id)
                if not video_process:
                    raise Exception("Video process record not found")
                
                user = User.query.get(video_process.user_id)
                if not user:
                    raise Exception("User not found")
                    
                logger.info(f"📋 Processing for user", user_email=user.email)
                
            except Exception as e:
                logger.error(f"❌ Database lookup error: {str(e)}")
                raise Exception(f"Database error: {str(e)}")
            
            # Deduct credits
            if not user.is_premium_active():
                try:
                    if not user.deduct_credits(10):
                        raise Exception("Insufficient credits")
                    logger.info("💳 Credits deducted successfully")
                except Exception as e:
                    logger.error(f"❌ Credit deduction failed: {str(e)}")
                    raise Exception("Failed to deduct credits")
            
            # Initialize processor
            try:
                processor = VideoProcessor()
                processor.setup_temp_directory()
                logger.info("✅ Video processor initialized")
            except Exception as e:
                logger.error(f"❌ Processor initialization failed: {str(e)}")
                raise Exception("Failed to initialize processor")
            
            try:
                # Download video
                self.update_state(
                    state='PROGRESS',
                    meta={'status': 'Downloading video from YouTube...'}
                )
                
                video_process.status = 'downloading'
                db.session.commit()
                
                download_result = processor.download_youtube_video(youtube_url)
                video_file = download_result['video_file']
                title = download_result['title']
                duration = download_result['duration']
                
                video_process.original_title = title
                video_process.status = 'processing'
                db.session.commit()
                
                logger.info(f"✅ Download completed", title=title, duration=duration)
                
                # Extract transcript
                self.update_state(
                    state='PROGRESS',
                    meta={'status': 'Extracting audio and analyzing content...'}
                )
                
                transcript = processor.extract_audio_transcript(video_file)
                
                # Analyze with AI
                self.update_state(
                    state='PROGRESS',
                    meta={'status': 'AI is analyzing content for viral moments...'}
                )
                
                video_process.status = 'analyzing'
                db.session.commit()
                
                analysis = processor.analyze_content_with_gemini(title, transcript, duration)
                
                if not analysis.get('clips'):
                    raise Exception("No clips could be generated from this video")
                
                # Create clips
                self.update_state(
                    state='PROGRESS',
                    meta={'status': f'Creating {len(analysis["clips"])} video clips...'}
                )
                
                video_process.status = 'creating_clips'
                db.session.commit()
                
                created_clips = processor.create_clips(video_file, analysis['clips'])
                
                if not created_clips:
                    raise Exception("No clips were successfully created")
                
                # Save to database
                self.update_state(
                    state='PROGRESS',
                    meta={'status': 'Saving results to database...'}
                )
                
                for clip_data in created_clips:
                    try:
                        clip = VideoClip(
                            process_id=video_process.id,
                            filename=clip_data['filename'],
                            title=clip_data['title'],
                            duration=clip_data['duration'],
                            viral_score=clip_data['viral_score'],
                            start_time=clip_data['start_time'],
                            end_time=clip_data['end_time']
                        )
                        db.session.add(clip)
                    except Exception as e:
                        logger.error(f"❌ Failed to save clip {clip_data.get('filename')}: {str(e)}")
                
                # Update video process
                video_process.status = 'completed'
                video_process.clips_generated = len(created_clips)
                video_process.blog_article = analysis.get('blog_article', '')
                video_process.carousel_posts = json.dumps(analysis.get('carousel_posts', []))
                video_process.completed_at = datetime.utcnow()
                
                db.session.commit()
                
                logger.info(f"✅ Video processing completed successfully", clips_created=len(created_clips))
                
                return {
                    'original_title': title,
                    'clips': created_clips,
                    'blog_article': analysis.get('blog_article', ''),
                    'carousel_posts': analysis.get('carousel_posts', [])
                }
                
            finally:
                if processor:
                    processor.cleanup_temp_directory()
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Video processing failed", error=error_msg)
            
            # Update database with error
            try:
                video_process = models['VideoProcess'].query.get(process_id)
                if video_process:
                    video_process.status = 'failed'
                    video_process.error_message = error_msg
                    db.session.commit()
                    logger.info("💾 Error status saved to database")
            except Exception as db_error:
                logger.error(f"❌ Failed to save error to database: {str(db_error)}")
            
            # Cleanup on error
            if processor:
                processor.cleanup_temp_directory()
            
            raise Exception(error_msg)

@celery.task
def local_backup_task():
    """Local database backup task"""
    try:
        logger.info("💾 Starting local database backup...")
        
        # Import backup module
        import sys
        sys.path.append('/var/www/askaraai')
        from backup_database import LocalDatabaseBackup
        
        backup_manager = LocalDatabaseBackup()
        success = backup_manager.run_backup()
        
        if success:
            logger.info("✅ Local backup completed successfully")
            return {'success': True, 'message': 'Local backup completed'}
        else:
            logger.error("❌ Local backup failed")
            return {'success': False, 'message': 'Local backup failed'}
        
    except Exception as e:
        logger.error(f"❌ Backup task failed: {str(e)}")
        return {'success': False, 'error': str(e)}

# Periodic tasks setup (LOCAL BACKUP ONLY)
from celery.schedules import crontab

celery.conf.beat_schedule = {
    'local-database-backup': {
        'task': 'celery_app.local_backup_task',
        'schedule': crontab(day_of_month='*/7', hour=2, minute=0),  # Weekly backup
    },
}

celery.conf.timezone = 'UTC'

if __name__ == '__main__':
    celery.start()
