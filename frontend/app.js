const API_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8000'
    : window.location.origin;

const videoPlayer = document.getElementById('mainVideo');
const queryInput = document.getElementById('queryInput');
const queryInputBottom = document.getElementById('queryInputBottom');
const sendBtn = document.getElementById('sendBtn');
const sendBtnBottom = document.getElementById('sendBtnBottom');
const chatHistory = document.getElementById('chatHistory');
const chatSection = document.querySelector('.chat-section');
let currentVideoId;

function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function activateChatMode() {
    chatSection.classList.remove('empty');
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
        btn.textContent = `Clip ${index + 1} : ${formatTime(clip.start_time_sec)}-${formatTime(clip.end_time_sec)}`;
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

function getActiveInput() {
    return chatSection.classList.contains('empty') ? queryInput : queryInputBottom;
}

function getActiveButton() {
    return chatSection.classList.contains('empty') ? sendBtn : sendBtnBottom;
}

async function askQuestion() {
    const activeInput = getActiveInput();
    const activeButton = getActiveButton();
    const query = activeInput.value.trim();
    if (!query) return;

    const useVideoClips = document.getElementById('useVideoClips').checked;

    // Activate chat mode if in empty state
    if (chatSection.classList.contains('empty')) {
        activateChatMode();
    }

    appendMessage('user', query);
    if (useVideoClips) {
        appendMessage('system', '🎬 Using detailed analysis mode (processing video clips)');
    }
    activeInput.value = '';
    activeButton.disabled = true;

    // Update the bottom input reference after state change
    const bottomInput = document.getElementById('queryInputBottom');
    const bottomButton = document.getElementById('sendBtnBottom');

    showLoading();

    try {
        const response = await fetch(`${API_URL}/ask`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query, video_id: currentVideoId, use_video_clips: useVideoClips})
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
        if (bottomButton) {
            bottomButton.disabled = false;
            bottomInput.focus();
        }
    }
}

sendBtn.addEventListener('click', askQuestion);
sendBtnBottom.addEventListener('click', askQuestion);

queryInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !sendBtn.disabled) {
        askQuestion();
    }
});

queryInputBottom.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !sendBtnBottom.disabled) {
        askQuestion();
    }
});

videoPlayer.addEventListener('loadedmetadata', () => {
    console.log('Video loaded - duration:', videoPlayer.duration);
});

function loadThumbnails() {
    document.querySelectorAll('.video-card').forEach(card => {
        const videoId = card.dataset.videoId;
        if (!videoId) return;

        fetch(`${API_URL}/video/${videoId}`)
            .then(response => response.json())
            .then(data => {
                const thumb = card.querySelector('.video-thumbnail');
                if (thumb) {
                    const source = thumb.querySelector('source');
                    source.src = data.url;
                    thumb.load();
                    thumb.addEventListener('loadeddata', function() {
                        this.currentTime = 5;
                    }, { once: true });
                }
            })
            .catch(error => {
                console.error(`Failed to load thumbnail for ${videoId}:`, error);
            });
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

            // Update video title
            const mainVideoCard = document.querySelector('.video-card.main-video');
            const titleElement = mainVideoCard.querySelector('.video-card-title');
            if (titleElement) {
                titleElement.textContent = videoTitle;
            }

            // Clear chat and reset to empty state
            chatHistory.innerHTML = '';
            chatSection.classList.add('empty');

            // Clear both inputs
            queryInput.value = '';
            queryInputBottom.value = '';
        })
        .catch(error => {
            console.error('Failed to load video:', error);
        });
}

document.querySelectorAll('.video-card').forEach(card => {
    card.addEventListener('click', () => switchVideo(card));
});

document.addEventListener('DOMContentLoaded', () => {
    const activeCard = document.querySelector('.video-card.main-video');
    if (activeCard) {
        const videoId = activeCard.dataset.videoId;
        currentVideoId = videoId;

        // Load the main video
        fetch(`${API_URL}/video/${videoId}`)
            .then(response => response.json())
            .then(data => {
                const source = videoPlayer.querySelector('source');
                source.src = data.url;
                videoPlayer.load();
            })
            .catch(error => {
                console.error('Failed to load main video:', error);
            });
    }
    loadThumbnails();
});

queryInput.focus();
