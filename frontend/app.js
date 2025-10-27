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

function truncateText(text, maxLength = 140) {
    if (!text) return '';
    const normalized = text.replace(/\s+/g, ' ').trim();
    return normalized.length > maxLength ? `${normalized.slice(0, maxLength).trim()}…` : normalized;
}

function renderFormattedFragment(text) {
    const escapeHtml = (value) => value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    const escaped = escapeHtml(text);
    const withCode = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');
    const withStrong = withCode.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    const withEmphasis = withStrong.replace(/(^|[\s(])\*([^*]+)\*(?=[\s).,!?:;]|$)/g, (_, prefix, content) => {
        return `${prefix}<em>${content}</em>`;
    });

    const template = document.createElement('template');
    template.innerHTML = withEmphasis;
    return template.content;
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
    return msg;
}

function createCitationBadge(index, clip) {
    const badge = document.createElement('button');
    badge.type = 'button';
    badge.className = 'citation-badge';
    badge.textContent = String(index + 1);
    badge.addEventListener('click', () => playClip(clip.start_time_sec));

    const timeRange = `${formatTime(clip.start_time_sec)} – ${formatTime(clip.end_time_sec)}`;
    const labelSummary = Array.isArray(clip.labels) && clip.labels.length
        ? ` • Labels: ${clip.labels.slice(0, 3).join(', ')}`
        : '';
    const ocrSummary = clip.ocr_text
        ? ` • OCR: ${truncateText(clip.ocr_text, 80)}`
        : '';
    const tooltip = `Clip ${index + 1} (${timeRange})${labelSummary}${ocrSummary}`;

    badge.title = tooltip;
    badge.setAttribute('aria-label', tooltip);

    return badge;
}

function appendAssistantMessage(text, clips = []) {
    const msg = document.createElement('div');
    msg.className = 'message assistant';

    const clipList = Array.isArray(clips) ? clips : [];
    let clipIndex = 0;
    let currentList = null;

    const appendSentenceWithCitation = (target, sentence) => {
        const cleaned = sentence.trim();
        if (!cleaned) return;

        if (target.childNodes.length) {
            target.appendChild(document.createTextNode(' '));
        }
        target.appendChild(renderFormattedFragment(cleaned));

        if (clipIndex < clipList.length) {
            target.appendChild(document.createTextNode(' '));
            target.appendChild(createCitationBadge(clipIndex, clipList[clipIndex]));
            clipIndex += 1;
        }
    };

    const renderLine = (lineText, target) => {
        const segments = lineText.match(/[^.!?]+[.!?]?/g) || [lineText];
        segments.forEach(segment => appendSentenceWithCitation(target, segment));
    };

    const lines = text.split('\n');

    lines.forEach(rawLine => {
        const line = rawLine.trim();
        if (!line) {
            currentList = null;
            return;
        }

        if (line.startsWith('- ')) {
            if (!currentList) {
                currentList = document.createElement('ul');
                currentList.className = 'message-list';
                msg.appendChild(currentList);
            }
            const item = document.createElement('li');
            item.className = 'message-list-item';
            renderLine(line.slice(2), item);
            currentList.appendChild(item);
        } else {
            currentList = null;
            const paragraph = document.createElement('p');
            paragraph.className = 'message-text';
            renderLine(line, paragraph);
            msg.appendChild(paragraph);
        }
    });

    if (clipIndex < clipList.length && msg.lastElementChild) {
        const last = msg.lastElementChild;
        while (clipIndex < clipList.length) {
            last.appendChild(document.createTextNode(' '));
            last.appendChild(createCitationBadge(clipIndex, clipList[clipIndex]));
            clipIndex += 1;
        }
    }

    chatHistory.appendChild(msg);
    chatHistory.scrollTop = chatHistory.scrollHeight;
    return msg;
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

        appendAssistantMessage(data.answer, data.clips);

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
    if (!videoId || videoId === currentVideoId) {
        return;
    }
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

    const useVideoClipsInitial = document.getElementById('useVideoClipsInitial');
    const useVideoClips = document.getElementById('useVideoClips');

    if (useVideoClipsInitial && useVideoClips) {
        useVideoClipsInitial.checked = true;
        useVideoClips.checked = true;

        useVideoClipsInitial.addEventListener('change', (event) => {
            useVideoClips.checked = event.target.checked;
        });
        useVideoClips.addEventListener('change', (event) => {
            useVideoClipsInitial.checked = event.target.checked;
        });
    }
});

queryInput.focus();
