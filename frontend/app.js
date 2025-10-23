const API_URL = 'http://localhost:8000';

const videoPlayer = document.getElementById('mainVideo');
const queryInput = document.getElementById('queryInput');
const sendBtn = document.getElementById('sendBtn');
const chatHistory = document.getElementById('chatHistory');
let currentVideoId = 'test_video';

function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function appendMessage(role, text) {
    const msg = document.createElement('div');
    msg.className = `message ${role}`;
    msg.textContent = text;
    chatHistory.appendChild(msg);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function displayClips(clips) {
    const container = document.createElement('div');
    container.className = 'clips-container';
    
    clips.forEach((clip, index) => {
        const btn = document.createElement('button');
        btn.className = 'clip-button';
        btn.textContent = `Clip ${index + 1}: ${formatTime(clip.start_time_sec)} - ${formatTime(clip.end_time_sec)}`;
        btn.onclick = () => playClip(clip.start_time_sec);
        container.appendChild(btn);
    });
    
    chatHistory.appendChild(container);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function playClip(startTime) {
    console.log('playClip called with startTime:', startTime);
    
    if (videoPlayer.readyState < 1) {
        console.log('Video not ready, waiting for loadedmetadata');
        videoPlayer.addEventListener('loadedmetadata', () => {
            playClip(startTime);
        }, { once: true });
        return;
    }
    
    videoPlayer.pause();
    console.log('Setting currentTime to:', startTime);
    videoPlayer.currentTime = startTime;
    
    const onSeeked = () => {
        console.log('Seeked complete, currentTime is now:', videoPlayer.currentTime);
        videoPlayer.play().catch(err => {
            console.error('Play failed:', err);
        });
    };
    
    videoPlayer.addEventListener('seeked', onSeeked, { once: true });
}

function showLoading() {
    const loading = document.createElement('div');
    loading.className = 'loading';
    loading.id = 'loading-indicator';
    loading.textContent = 'Searching...';
    chatHistory.appendChild(loading);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function hideLoading() {
    const loading = document.getElementById('loading-indicator');
    if (loading) {
        loading.remove();
    }
}

async function askQuestion() {
    const query = queryInput.value.trim();
    if (!query) return;
    
    appendMessage('user', query);
    queryInput.value = '';
    sendBtn.disabled = true;
    
    showLoading();
    
    try {
        const response = await fetch(`${API_URL}/ask`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query, video_id: currentVideoId})
        });
        
        hideLoading();
        
        if (!response.ok) {
            const error = await response.json();
            appendMessage('error', error.detail || 'Failed to get response');
            return;
        }
        
        const data = await response.json();
        
        appendMessage('assistant', data.answer);
        
        if (data.clips && data.clips.length > 0) {
            displayClips(data.clips);
        }
        
    } catch (error) {
        hideLoading();
        appendMessage('error', 'Network error: ' + error.message);
    } finally {
        sendBtn.disabled = false;
        queryInput.focus();
    }
}

sendBtn.addEventListener('click', askQuestion);

queryInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !sendBtn.disabled) {
        askQuestion();
    }
});

videoPlayer.addEventListener('loadedmetadata', () => {
    console.log('Video loaded - duration:', videoPlayer.duration);
});

function loadThumbnails() {
    document.querySelectorAll('.video-thumbnail').forEach(thumb => {
        thumb.addEventListener('loadeddata', function() {
            this.currentTime = 5;
        });
        thumb.load();
    });
}

function switchVideo(card) {
    if (card.classList.contains('upload-card') || card.classList.contains('processing')) {
        return;
    }
    
    const videoId = card.dataset.videoId;
    const videoTitle = card.dataset.title;
    
    document.querySelectorAll('.video-card').forEach(c => c.classList.remove('active'));
    card.classList.add('active');
    
    currentVideoId = videoId;
    
    // Get signed URL from backend
    fetch(`${API_URL}/video/${videoId}`)
        .then(response => response.json())
        .then(data => {
            const source = videoPlayer.querySelector('source');
            source.src = data.url;
            videoPlayer.load();
            
            document.getElementById('videoTitle').textContent = videoTitle;
            chatHistory.innerHTML = '';
        })
        .catch(error => {
            console.error('Failed to load video:', error);
            // Fallback to local file
            const videoSrc = card.dataset.src;
            const source = videoPlayer.querySelector('source');
            source.src = videoSrc;
            videoPlayer.load();
            
            document.getElementById('videoTitle').textContent = videoTitle;
            chatHistory.innerHTML = '';
        });
}

document.querySelectorAll('.video-card:not(.upload-card)').forEach(card => {
    card.addEventListener('click', () => switchVideo(card));
});

document.getElementById('uploadCard').addEventListener('click', () => {
    document.getElementById('videoUpload').click();
});

document.getElementById('videoUpload').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    const videoId = 'video_' + Date.now();
    const videoURL = URL.createObjectURL(file);
    
    const newCard = document.createElement('div');
    newCard.className = 'video-card processing';
    newCard.dataset.videoId = videoId;
    newCard.dataset.src = videoURL;
    newCard.dataset.title = file.name.replace(/\.[^/.]+$/, '');
    
    newCard.innerHTML = `
        <video class="video-thumbnail" muted>
            <source src="${videoURL}" type="video/mp4">
        </video>
        <div class="video-card-info">
            <span class="video-card-title">${file.name.replace(/\.[^/.]+$/, '')}</span>
            <span class="video-card-duration">...</span>
        </div>
    `;
    
    const uploadCard = document.getElementById('uploadCard');
    uploadCard.parentNode.insertBefore(newCard, uploadCard);
    
    const thumb = newCard.querySelector('.video-thumbnail');
    thumb.addEventListener('loadeddata', function() {
        this.currentTime = 5;
        const duration = Math.floor(this.duration);
        const mins = Math.floor(duration / 60);
        const secs = duration % 60;
        newCard.querySelector('.video-card-duration').textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
    });
    thumb.load();
    
    try {
        const formData = new FormData();
        formData.append('video', file);
        formData.append('video_id', videoId);
        
        const response = await fetch(`${API_URL}/upload`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error('Upload failed');
        }
        
        newCard.classList.remove('processing');
        newCard.addEventListener('click', () => switchVideo(newCard));
        
    } catch (error) {
        console.error('Upload error:', error);
        newCard.remove();
        alert('Upload failed: ' + error.message);
    }
    
    e.target.value = '';
});

loadThumbnails();
queryInput.focus();

