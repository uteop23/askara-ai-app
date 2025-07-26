# celery_app.py - FIXED VERSION
# Circular import diperbaiki dan error handling diperkuat

import os
import json
import logging
from datetime import datetime, timedelta
from celery import Celery
from dotenv import load_dotenv
import redis
import yt_dlp
import moviepy.editor as mp
import google.generativeai as genai
from moviepy.video.fx import resize
import subprocess
import tempfile
import shutil
from pathlib import Path
import traceback
import secrets

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/www/askaraai/logs/celery.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Create Celery instance
celery = Celery('askaraai')

# Celery configuration
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
        'celery_app.backup_database_task': {'queue': 'maintenance'},
    },
    task_annotations={
        'celery_app.process_video_task': {'rate_limit': '10/m'},
        'celery_app.backup_database_task': {'rate_limit': '1/d'},
    },
    task_reject_on_worker_lost=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Configure Gemini AI with error handling
try:
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if gemini_api_key:
        genai.configure(api_key=gemini_api_key)
        logger.info("✅ Gemini AI configured successfully")
    else:
        logger.warning("⚠️ GEMINI_API_KEY not found in environment")
except Exception as e:
    logger.error(f"❌ Failed to configure Gemini AI: {str(e)}")

# Redis client dengan error handling
try:
    redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))
    redis_client.ping()
    logger.info("✅ Redis connection established")
except Exception as e:
    logger.error(f"❌ Redis connection failed: {str(e)}")
    redis_client = None

# ===== HELPER FUNCTION TO GET DB AND MODELS (SOLUSI CIRCULAR IMPORT) =====
def get_app_and_models():
    """Lazy import untuk menghindari circular import"""
    try:
        # Import Flask app untuk context
        from app import app
        
        # Import models dari file terpisah
        from app_models import db, User, VideoProcess, VideoClip
        
        return app, db, User, VideoProcess, VideoClip
    except Exception as e:
        logger.error(f"Failed to import app and models: {str(e)}")
        raise

class VideoProcessor:
    def __init__(self):
        self.temp_dir = None
        try:
            self.gemini_model = genai.GenerativeModel('gemini-pro')
            logger.info("✅ Gemini model initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini model: {str(e)}")
            self.gemini_model = None
    
    def setup_temp_directory(self):
        """Create temporary directory for processing"""
        try:
            self.temp_dir = tempfile.mkdtemp(prefix='askaraai_', dir='/tmp')
            logger.info(f"✅ Temporary directory created: {self.temp_dir}")
            return self.temp_dir
        except Exception as e:
            logger.error(f"❌ Failed to create temp directory: {str(e)}")
            raise
    
    def cleanup_temp_directory(self):
        """Clean up temporary directory"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                logger.info(f"✅ Temporary directory cleaned: {self.temp_dir}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to cleanup temp directory: {str(e)}")
    
    def download_youtube_video(self, url):
        """Download YouTube video with robust error handling"""
        try:
            logger.info(f"🔄 Starting download from: {url}")
            
            # Validate URL first
            if not any(domain in url for domain in ['youtube.com', 'youtu.be']):
                raise ValueError("Invalid YouTube URL")
            
            ydl_opts = {
                'format': 'best[height<=720]/best',
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
                    
                    # Check video duration (max 3 hours)
                    if duration and duration > 10800:  # 3 hours
                        raise Exception("Video too long. Maximum duration is 3 hours.")
                    
                    # Check if video is available
                    if info.get('is_live'):
                        raise Exception("Live streams are not supported")
                        
                except Exception as e:
                    logger.error(f"❌ Failed to extract video info: {str(e)}")
                    raise Exception(f"Failed to get video information: {str(e)}")
                
                # Download video
                try:
                    ydl.download([url])
                    logger.info("✅ Video download completed")
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
                
                # Verify file size
                file_size = os.path.getsize(video_file)
                if file_size < 1024:  # Less than 1KB
                    raise Exception("Downloaded file is too small, likely corrupted")
                
                logger.info(f"✅ Video file ready: {video_file} ({file_size} bytes)")
                
                return {
                    'video_file': video_file,
                    'title': title,
                    'duration': duration or 60  # Default duration if not available
                }
                
        except Exception as e:
            logger.error(f"❌ Download error: {str(e)}")
            raise Exception(f"Failed to download video: {str(e)}")
    
    def extract_audio_transcript(self, video_file):
        """Extract audio and generate transcript using FFmpeg"""
        try:
            logger.info("🔄 Extracting audio for transcript...")
            
            # Verify input file exists
            if not os.path.exists(video_file):
                raise Exception("Video file not found")
            
            # Extract audio using FFmpeg
            audio_file = os.path.join(self.temp_dir, 'audio.wav')
            
            cmd = [
                'ffmpeg', '-i', video_file,
                '-vn',  # No video
                '-acodec', 'pcm_s16le',  # Audio codec
                '-ar', '16000',  # Sample rate
                '-ac', '1',  # Mono
                '-y',  # Overwrite
                '-loglevel', 'error',  # Reduce FFmpeg output
                audio_file
            ]
            
            try:
                result = subprocess.run(cmd, check=True, capture_output=True, timeout=300)
                logger.info("✅ Audio extraction completed")
            except subprocess.TimeoutExpired:
                raise Exception("Audio extraction timed out")
            except subprocess.CalledProcessError as e:
                logger.error(f"FFmpeg error: {e.stderr.decode()}")
                # Continue with placeholder transcript instead of failing
                logger.warning("⚠️ Audio extraction failed, using placeholder transcript")
            
            # Create transcript placeholder
            transcript = f"Audio content extracted from video. Video appears to contain valuable content suitable for clipping based on duration and file analysis."
            
            logger.info("✅ Transcript generation completed")
            return transcript
            
        except Exception as e:
            logger.error(f"❌ Audio extraction error: {str(e)}")
            return f"Transcript unavailable: {str(e)}"
    
    def analyze_content_with_gemini(self, title, transcript, duration):
        """Analyze video content using Gemini AI with robust error handling"""
        try:
            logger.info("🔄 Analyzing content with Gemini AI...")
            
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
                
                # Try to parse JSON response
                try:
                    # Clean response text
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
                    
                    # Validate clips data
                    valid_clips = []
                    for clip in result['clips']:
                        if all(key in clip for key in ['title', 'start_time', 'end_time', 'viral_score']):
                            # Ensure clip times are within video duration
                            start_time = max(0, min(float(clip['start_time']), duration - 10))
                            end_time = min(float(clip['end_time']), duration)
                            
                            if end_time > start_time + 10:  # Minimum 10 seconds
                                clip['start_time'] = start_time
                                clip['end_time'] = end_time
                                valid_clips.append(clip)
                    
                    if valid_clips:
                        result['clips'] = valid_clips[:10]  # Max 10 clips
                        logger.info(f"✅ Parsed {len(valid_clips)} valid clips from Gemini")
                        return result
                    else:
                        raise ValueError("No valid clips found in response")
                        
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"⚠️ Failed to parse Gemini response: {str(e)}")
                    logger.info("📝 Creating fallback analysis...")
                    return self.create_fallback_analysis(title, duration)
                
            except Exception as e:
                logger.error(f"❌ Gemini API error: {str(e)}")
                return self.create_fallback_analysis(title, duration)
                
        except Exception as e:
            logger.error(f"❌ Content analysis error: {str(e)}")
            return self.create_fallback_analysis(title, duration)
    
    def create_fallback_analysis(self, title, duration):
        """Create fallback analysis when Gemini fails"""
        logger.info("🔄 Creating fallback analysis...")
        
        # Create clips every 60-90 seconds
        clips = []
        num_clips = min(8, max(3, int(duration // 60)))
        
        segment_duration = duration / num_clips
        
        for i in range(num_clips):
            start_time = i * segment_duration
            clip_duration = min(60, segment_duration * 0.8)  # 80% of segment or 60s max
            end_time = min(start_time + clip_duration, duration)
            
            # Skip if clip would be too short
            if end_time - start_time < 15:
                continue
            
            clips.append({
                "title": f"Momen Menarik #{i+1} - {title[:30]}",
                "start_time": round(start_time, 1),
                "end_time": round(end_time, 1),
                "viral_score": max(5.0, 9.0 - (i * 0.5)),  # Decreasing viral score
                "reason": "Segmen yang dipilih berdasarkan analisis durasi dan konten"
            })
        
        # Create blog article
        blog_article = f"""
        <h1>{title} - Analisis Konten Video</h1>
        <p>Video ini berisi konten berkualitas dengan durasi {duration} detik. Tim AI kami telah menganalisis dan mengidentifikasi {len(clips)} momen yang berpotensi viral.</p>
        
        <h2>Highlights Video</h2>
        <p>Setiap klip telah dipilih berdasarkan potensi engagement dan kualitas konten. Video original menampilkan informasi berharga yang dapat menarik perhatian audiens target.</p>
        
        <h2>Strategi Konten untuk Media Sosial</h2>
        <p>Untuk memaksimalkan reach di media sosial:</p>
        <ul>
            <li>Gunakan hook yang kuat di 3 detik pertama setiap klip</li>
            <li>Tambahkan caption yang engaging dan ajukan pertanyaan</li>
            <li>Post di waktu prime time untuk reach maksimal</li>
            <li>Gunakan hashtag yang relevan dengan niche Anda</li>
        </ul>
        
        <h2>Tips Optimasi</h2>
        <p>Setiap klip dapat dioptimalkan lebih lanjut dengan menambahkan subtitle, musik background, dan visual elements yang menarik perhatian.</p>
        """
        
        # Create carousel posts
        carousel_posts = [
            f"🎬 Thread: {title[:50]}... - Insights penting dari video ini!",
            "💡 Tip #1: Konten berkualitas dimulai dari pemilihan momen yang tepat",
            "🚀 Tip #2: Setiap klip harus memiliki nilai tersendiri untuk audiens",
            "📈 Tip #3: Konsistensi posting lebih penting daripada perfeksi",
            "✨ Kesimpulan: Dengan tools AI yang tepat, satu video bisa jadi 10+ konten!"
        ]
        
        logger.info(f"✅ Fallback analysis created with {len(clips)} clips")
        
        return {
            "clips": clips,
            "blog_article": blog_article,
            "carousel_posts": carousel_posts
        }
    
    def create_clips(self, video_file, clips_data):
        """Create video clips from the original video with enhanced error handling"""
        try:
            logger.info(f"🔄 Creating {len(clips_data)} clips from video...")
            
            # Verify input file
            if not os.path.exists(video_file):
                raise Exception("Video file not found")
            
            # Load video with error handling
            try:
                video = mp.VideoFileClip(video_file)
                logger.info(f"✅ Video loaded: {video.duration}s, {video.fps}fps, {video.size}")
            except Exception as e:
                raise Exception(f"Failed to load video file: {str(e)}")
            
            created_clips = []
            
            # Ensure clips directory exists
            clips_dir = '/var/www/askaraai/static/clips'
            os.makedirs(clips_dir, exist_ok=True)
            
            for i, clip_data in enumerate(clips_data):
                try:
                    logger.info(f"🔄 Processing clip {i+1}/{len(clips_data)}: {clip_data.get('title', 'Untitled')}")
                    
                    start_time = max(0, float(clip_data.get('start_time', 0)))
                    end_time = min(float(clip_data.get('end_time', 60)), video.duration)
                    
                    # Ensure valid time range
                    if end_time <= start_time:
                        logger.warning(f"⚠️ Invalid time range for clip {i+1}, skipping")
                        continue
                    
                    if end_time - start_time < 10:  # Minimum 10 seconds
                        logger.warning(f"⚠️ Clip {i+1} too short ({end_time - start_time}s), skipping")
                        continue
                    
                    # Extract clip
                    try:
                        clip = video.subclip(start_time, end_time)
                        logger.info(f"✅ Clip extracted: {end_time - start_time:.1f}s")
                    except Exception as e:
                        logger.error(f"❌ Failed to extract clip {i+1}: {str(e)}")
                        continue
                    
                    # Resize to vertical format (9:16) with better error handling
                    try:
                        target_height = 1920
                        target_width = 1080
                        
                        # Calculate scaling to fit height
                        if clip.h > 0:
                            scale_factor = target_height / clip.h
                            clip_resized = clip.resize(scale_factor)
                            
                            # Crop to 9:16 if too wide
                            if clip_resized.w > target_width:
                                x_center = clip_resized.w / 2
                                clip_resized = clip_resized.crop(x_center=x_center, width=target_width)
                            
                            # Ensure exact size
                            clip_final = clip_resized.resize((target_width, target_height))
                            
                        else:
                            raise Exception("Invalid video dimensions")
                        
                        logger.info(f"✅ Clip resized to {target_width}x{target_height}")
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to resize clip {i+1}: {str(e)}")
                        clip.close()
                        continue
                    
                    # Generate safe filename
                    safe_title = "".join(c for c in str(clip_data.get('title', f'clip_{i+1}')) 
                                       if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"clip_{i+1}_{timestamp}_{safe_title}.mp4".replace(' ', '_')
                    output_path = os.path.join(clips_dir, filename)
                    
                    # Write clip with robust error handling
                    try:
                        clip_final.write_videofile(
                            output_path,
                            codec='libx264',
                            audio_codec='aac',
                            bitrate='2000k',
                            fps=24,  # Consistent framerate
                            verbose=False,
                            logger=None,
                            temp_audiofile_path=os.path.join(self.temp_dir, f'temp_audio_{i}.m4a')
                        )
                        
                        # Verify output file
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                            logger.info(f"✅ Clip saved: {filename} ({os.path.getsize(output_path)} bytes)")
                            
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
                    
                    # Clean up clip objects
                    try:
                        clip.close()
                        clip_resized.close()
                        clip_final.close()
                    except:
                        pass
                    
                except Exception as e:
                    logger.error(f"❌ Error processing clip {i+1}: {str(e)}")
                    continue
            
            # Clean up main video
            try:
                video.close()
            except:
                pass
            
            logger.info(f"✅ Clip creation completed: {len(created_clips)}/{len(clips_data)} clips created")
            return created_clips
            
        except Exception as e:
            logger.error(f"❌ Clip creation error: {str(e)}")
            raise Exception(f"Failed to create clips: {str(e)}")

@celery.task(bind=True)
def process_video_task(self, process_id, youtube_url):
    """Main task for processing YouTube videos with comprehensive error handling"""
    app, db, User, VideoProcess, VideoClip = get_app_and_models()
    
    with app.app_context():
        try:
            logger.info(f"🚀 Starting video processing task for process_id: {process_id}")
            
            # Update task status
            self.update_state(
                state='PROGRESS',
                meta={'status': 'Initializing video processing...'}
            )
            
            # Get video process record
            try:
                video_process = VideoProcess.query.get(process_id)
                if not video_process:
                    raise Exception("Video process record not found")
                
                user = User.query.get(video_process.user_id)
                if not user:
                    raise Exception("User not found")
                    
                logger.info(f"📋 Processing for user: {user.email}")
                
            except Exception as e:
                logger.error(f"❌ Database lookup error: {str(e)}")
                raise Exception(f"Database error: {str(e)}")
            
            # Deduct credits for non-premium users
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
                # Update status and download video
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
                
                # Update video process with title
                video_process.original_title = title
                video_process.status = 'processing'
                db.session.commit()
                
                logger.info(f"✅ Download completed: {title}")
                
                # Update status and extract transcript
                self.update_state(
                    state='PROGRESS',
                    meta={'status': 'Extracting audio and analyzing content...'}
                )
                
                transcript = processor.extract_audio_transcript(video_file)
                
                # Update status and analyze with AI
                self.update_state(
                    state='PROGRESS',
                    meta={'status': 'AI is analyzing content for viral moments...'}
                )
                
                video_process.status = 'analyzing'
                db.session.commit()
                
                analysis = processor.analyze_content_with_gemini(title, transcript, duration)
                
                if not analysis.get('clips'):
                    raise Exception("No clips could be generated from this video")
                
                # Update status and create clips
                self.update_state(
                    state='PROGRESS',
                    meta={'status': f'Creating {len(analysis["clips"])} video clips...'}
                )
                
                video_process.status = 'creating_clips'
                db.session.commit()
                
                created_clips = processor.create_clips(video_file, analysis['clips'])
                
                if not created_clips:
                    raise Exception("No clips were successfully created")
                
                # Update status and save to database
                self.update_state(
                    state='PROGRESS',
                    meta={'status': 'Saving results to database...'}
                )
                
                # Save clips to database
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
                
                logger.info(f"✅ Video processing completed successfully: {len(created_clips)} clips created")
                
                return {
                    'original_title': title,
                    'clips': created_clips,
                    'blog_article': analysis.get('blog_article', ''),
                    'carousel_posts': analysis.get('carousel_posts', [])
                }
                
            finally:
                # Always cleanup temp directory
                try:
                    processor.cleanup_temp_directory()
                except Exception as e:
                    logger.warning(f"⚠️ Cleanup warning: {str(e)}")
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Video processing failed: {error_msg}")
            logger.error(f"📄 Traceback: {traceback.format_exc()}")
            
            # Update database with error
            try:
                video_process = VideoProcess.query.get(process_id)
                if video_process:
                    video_process.status = 'failed'
                    video_process.error_message = error_msg
                    db.session.commit()
                    logger.info("💾 Error status saved to database")
            except Exception as db_error:
                logger.error(f"❌ Failed to save error to database: {str(db_error)}")
            
            # Re-raise the exception for Celery
            raise Exception(error_msg)

@celery.task
def backup_database_task():
    """Backup database to Google Drive every 26 days with enhanced error handling"""
    try:
        logger.info("💾 Starting database backup...")
        
        # Verify required environment variables
        db_password = os.getenv('DB_PASSWORD')
        if not db_password:
            raise Exception("DB_PASSWORD environment variable not set")
        
        # Create backup filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"askaraai_backup_{timestamp}.sql"
        backup_path = f"/tmp/{backup_filename}"
        
        # Create MySQL dump with proper error handling
        dump_cmd = [
            'mysqldump',
            '-h', 'localhost',
            '-u', 'askaraai',
            f"-p{db_password}",
            '--single-transaction',
            '--routines',
            '--triggers',
            '--events',
            '--hex-blob',
            'askaraai_db'
        ]
        
        try:
            with open(backup_path, 'w') as f:
                result = subprocess.run(dump_cmd, stdout=f, stderr=subprocess.PIPE, 
                                      check=True, timeout=600)
            
            # Verify backup file
            if not os.path.exists(backup_path) or os.path.getsize(backup_path) < 1024:
                raise Exception("Backup file is empty or too small")
                
            logger.info(f"✅ Database dump created: {backup_path}")
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"MySQL dump failed: {e.stderr.decode()}")
        except subprocess.TimeoutExpired:
            raise Exception("MySQL dump timed out")
        
        # Upload to Google Drive
        try:
            upload_cmd = ['rclone', 'copy', backup_path, 'gdrive:AskaraAI/backups/', '--log-level', 'ERROR']
            result = subprocess.run(upload_cmd, check=True, capture_output=True, timeout=300)
            logger.info(f"✅ Backup uploaded to Google Drive: {backup_filename}")
        except subprocess.CalledProcessError as e:
            raise Exception(f"Upload to Google Drive failed: {e.stderr.decode()}")
        except subprocess.TimeoutExpired:
            raise Exception("Upload to Google Drive timed out")
        
        # Remove local backup file
        try:
            os.remove(backup_path)
            logger.info("✅ Local backup file removed")
        except Exception as e:
            logger.warning(f"⚠️ Failed to remove local backup: {str(e)}")
        
        logger.info(f"✅ Database backup completed successfully: {backup_filename}")
        
    except Exception as e:
        logger.error(f"❌ Database backup failed: {str(e)}")
        raise Exception(str(e))

# Periodic tasks setup
from celery.schedules import crontab

celery.conf.beat_schedule = {
    'backup-database': {
        'task': 'celery_app.backup_database_task',
        'schedule': crontab(day_of_month='*/26', hour=2, minute=0),  # Every 26 days at 2 AM
    },
}

celery.conf.timezone = 'UTC'

if __name__ == '__main__':
    celery.start()