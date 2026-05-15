// Conversation Page JavaScript with WebSocket

document.addEventListener('DOMContentLoaded', function() {
    // Elements
    const messagesContainer = document.getElementById('messages-container');
    const messageForm = document.getElementById('message-form');
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const connectionIndicator = document.getElementById('connection-indicator');
    const downloadTranscriptBtn = document.getElementById('download-transcript');
    const endConversationBtn = document.getElementById('end-conversation');
    const quickResponseButtons = document.querySelectorAll('.quick-response');
    
    // WebSocket connection
    let socket;
    let connected = false;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 5;
    let historyLoaded = false;
    let historyLoadInProgress = false;
    let historyRetryAttempts = 0;
    const maxHistoryRetries = 5;
    const historyRetryDelayMs = 2000;
    
    // Initial setup
    initializeWebSocket();
    renderExistingMarkdownMessages();
    scrollToBottom();
    
    // Join the conversation when the page loads
    fetch(`/api/conversations/${conversationId}/join`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Agent-ID': agentId,
            'X-Agent-Name': agentName
        }
    }).catch(error => {
        console.error('Error joining conversation:', error);
    });
    
    // Automatically load conversation history when agent joins
    console.log(`[DEBUG] Page loaded - conversationId: ${conversationId}`);
    console.log(`[DEBUG] Calling loadConversationHistory()`);
    loadConversationHistory();
    
    // Initialize WebSocket connection
    function initializeWebSocket() {
        // Close existing connection if any
        if (socket) {
            socket.close();
        }
        
        // Determine WebSocket URL (ws or wss)
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const queryParams = new URLSearchParams({
            client_type: 'agent',
            agent_name: agentName,
            agent_id: agentId
        });
        const wsUrl = `${protocol}//${window.location.host}/ws/conversation/${conversationId}?${queryParams.toString()}`;
        
        // Create new WebSocket
        socket = new WebSocket(wsUrl);
        
        // WebSocket event handlers
        socket.onopen = handleSocketOpen;
        socket.onmessage = handleSocketMessage;
        socket.onclose = handleSocketClose;
        socket.onerror = handleSocketError;
        
        // Update UI to show connecting status
        updateConnectionStatus('connecting');
    }
    
    // Handle WebSocket connection open
    function handleSocketOpen() {
        console.log('WebSocket connection established');
        connected = true;
        reconnectAttempts = 0;
        updateConnectionStatus('connected');

        // Identify this connection as an agent to the server
        try {
            socket.send(JSON.stringify({
                type: 'client_identification',
                client_type: 'agent',
                agent_name: agentName,
                agent_id: agentId,
                timestamp: new Date().toISOString()
            }));
        } catch (identError) {
            console.error('Failed to send identification payload:', identError);
        }
        
        // Send a system message for agent joining
        addMessageToUI({
            role: 'system',
            content: `You have successfully connected to the conversation as ${agentName}.`,
            timestamp: new Date().toISOString()
        });
    }
    
    // Handle incoming WebSocket messages
    function handleSocketMessage(event) {
        try {
            const data = JSON.parse(event.data);
            console.log('Received message:', data);
            
            // Handle different message types
            if (data.type === 'agent_joined' && data.agent !== agentName) {
                // Another agent joined
                addMessageToUI({
                    role: 'system',
                    content: `Agent ${data.agent} has joined the conversation.`,
                    timestamp: data.timestamp
                });
            } else if (data.type === 'agent_left') {
                // Agent left
                addMessageToUI({
                    role: 'system',
                    content: `Agent ${data.agent} has left the conversation.`,
                    timestamp: data.timestamp
                });
            } else if (data.type === 'connection_established') {
                // Connection confirmed
                console.log('Connection confirmed by server');
            } else if (data.role) {
                // Regular message with role (user, agent, or system)
                addMessageToUI(data);
            }
        } catch (error) {
            console.error('Error parsing message:', error);
        }
    }
    
    // Handle WebSocket connection close
    function handleSocketClose(event) {
        console.log('WebSocket connection closed', event);
        connected = false;
        updateConnectionStatus('disconnected');
        
        // Attempt to reconnect if not a normal closure
        if (event.code !== 1000 && reconnectAttempts < maxReconnectAttempts) {
            reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 10000);
            
            addMessageToUI({
                role: 'system',
                content: `Connection lost. Attempting to reconnect (${reconnectAttempts}/${maxReconnectAttempts})...`,
                timestamp: new Date().toISOString()
            });
            
            setTimeout(initializeWebSocket, delay);
        } else if (reconnectAttempts >= maxReconnectAttempts) {
            addMessageToUI({
                role: 'system',
                content: 'Connection lost. Maximum reconnection attempts reached. Please refresh the page.',
                timestamp: new Date().toISOString()
            });
        }
    }
    
    // Handle WebSocket errors
    function handleSocketError(error) {
        console.error('WebSocket error:', error);
        updateConnectionStatus('error');
    }
    
    // Update connection status indicator
    function updateConnectionStatus(status) {
        // Remove all state classes
        connectionIndicator.classList.remove('connected', 'connecting', 'disconnected', 'error');
        
        // Set indicator based on status
        let dotClass = 'bg-yellow-400';
        let statusText = 'Connecting...';
        let textClass = 'text-yellow-600';
        
        if (status === 'connected') {
            dotClass = 'bg-green-500';
            statusText = 'Connected';
            textClass = 'text-green-600';
        } else if (status === 'disconnected') {
            dotClass = 'bg-red-500';
            statusText = 'Disconnected';
            textClass = 'text-red-600';
        } else if (status === 'error') {
            dotClass = 'bg-red-500';
            statusText = 'Connection error';
            textClass = 'text-red-600';
        }
        
        // Update the indicator
        connectionIndicator.innerHTML = `
            <div class="h-2.5 w-2.5 rounded-full ${dotClass} mr-2"></div>
            <span class="text-sm ${textClass}">${statusText}</span>
        `;
        
        // Add state class
        connectionIndicator.classList.add(status);
    }
    
    // Add message to UI
    function addMessageToUI(message) {
        // Determine message type and create wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'message-wrapper mb-4';
        
        // Add historical message styling if applicable
        if (message.isHistorical) {
            wrapper.classList.add('opacity-75');
        }
        
        if (message.role === 'agent') {
            wrapper.classList.add('justify-end');
        } else if (message.role === 'user' || message.role === 'User') {
            wrapper.classList.add('justify-start');
        } else if (message.role === 'assistant' || message.role === 'Lucy') {
            wrapper.classList.add('justify-start');  // Lucy messages align left like user messages
        } else if (message.role === 'system') {
            wrapper.classList.add('justify-center');
        }
        
        // Format timestamp with timezone
        let timeDisplay = 'Just now';
        if (message.timestamp) {
            try {
                const date = new Date(message.timestamp);
                timeDisplay = date.toLocaleTimeString([], { 
                    hour: '2-digit', 
                    minute: '2-digit',
                    timeZoneName: 'short'
                });
            } catch (e) {
                console.error('Error formatting timestamp:', e);
            }
        }
        
        // Create message content
        if (message.role === 'system') {
            const systemContent = renderMarkdown(String(message.content || ''));
            wrapper.innerHTML = `
                <div class="inline-block px-4 py-2 rounded-md bg-gray-100 text-sm text-gray-700">
                    ${systemContent}
                </div>
            `;
        } else {
            // Determine author name
            let authorName = 'User';
            if (message.role === 'agent') {
                authorName = agentName;
            } else if (message.role === 'assistant' || message.role === 'Lucy') {
                authorName = 'Lucy (AI)';
            } else if (message.role === 'user' || message.role === 'User') {
                authorName = 'User';
            }
            
            // Determine message style class
            let messageClass = 'user-message';
            if (message.role === 'agent') {
                messageClass = 'agent-message';
            } else if (message.role === 'assistant' || message.role === 'Lucy') {
                messageClass = 'assistant-message';  // Add a new class for Lucy/AI messages
            }
            
            const htmlContent = renderMarkdown(String(message.content || ''));
            wrapper.innerHTML = `
                <div class="${messageClass}">
                    <div class="message-header">
                        <span class="message-author">${authorName}</span>
                        <span class="message-time">${timeDisplay}${message.isHistorical ? ' (from before handoff)' : ''}</span>
                    </div>
                    <div class="message-content">
                        ${htmlContent}
                    </div>
                </div>
            `;
        }
        
        // Add to container and scroll to bottom
        messagesContainer.appendChild(wrapper);
        scrollToBottom();
    }
    
    // Scroll messages container to bottom
    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function escapeHtml(text) {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function renderMarkdown(text) {
        const safeText = String(text || '');
        if (window.marked) {
            try {
                const markdownSource = window.DOMPurify ? safeText : escapeHtml(safeText);
                const rawHtml = window.marked.parse(markdownSource, { breaks: true, gfm: true });
                if (window.DOMPurify) {
                    return window.DOMPurify.sanitize(rawHtml);
                }
                return rawHtml;
            } catch (e) {
                console.error('Markdown render failed:', e);
            }
        }
        return escapeHtml(safeText).replace(/\n/g, '<br>');
    }

    function renderExistingMarkdownMessages() {
        document
            .querySelectorAll('.message-content[data-markdown-content]:not([data-markdown-rendered])')
            .forEach(element => {
                element.innerHTML = renderMarkdown(element.textContent || '');
                element.setAttribute('data-markdown-rendered', 'true');
            });
    }
    
    // Send message via WebSocket
    function sendMessage(content) {
        if (!connected || !content.trim()) {
            return false;
        }
        
        const message = {
            role: 'agent',
            type: 'agent_message',
            content: content.trim(),
            agent_name: agentName,
            agent_id: agentId,
            source_client: 'agent',
            timestamp: new Date().toISOString()
        };
        
        try {
            // Send to WebSocket
            socket.send(JSON.stringify(message));
            
            // Immediately add to UI so agent can see their own message
            addMessageToUI(message);
            
            messageInput.value = '';
            return true;
        } catch (error) {
            console.error('Error sending message:', error);
            return false;
        }
    }
    
    // Event Listeners
    messageForm.addEventListener('submit', function(e) {
        e.preventDefault();
        sendMessage(messageInput.value);
    });
    
    // Allow Enter to send, Shift+Enter for new line
    messageInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage(messageInput.value);
        }
    });
    
    // Quick response buttons
    quickResponseButtons.forEach(button => {
        button.addEventListener('click', function() {
            const text = this.getAttribute('data-text');
            messageInput.value = text;
            sendMessage(text);
        });
    });
    
    // Download transcript
    downloadTranscriptBtn.addEventListener('click', async function() {
        try {
            const response = await fetch(`/api/conversations/${conversationId}/transcript`);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            
            // Create a blob and download link
            const blob = new Blob([data.transcript], { type: 'text/plain' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = `transcript-${conversationId}.txt`;
            
            // Trigger download
            document.body.appendChild(a);
            a.click();
            
            // Clean up
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (error) {
            console.error('Error downloading transcript:', error);
            alert('Error downloading transcript. Please try again.');
        }
    });
    
    // End conversation
    endConversationBtn.addEventListener('click', async function() {
        if (confirm('Are you sure you want to end this conversation?')) {
            try {
                await fetch(`/api/conversations/${conversationId}/leave`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Agent-ID': agentId,
                        'X-Agent-Name': agentName
                    }
                });
                
                sendMessage('The agent has ended this conversation. Thank you for using our support service.');
                
                // Redirect to portal after a short delay
                setTimeout(() => {
                    window.location.href = '/agent/portal';
                }, 1500);
            } catch (error) {
                console.error('Error ending conversation:', error);
                alert('Error ending conversation. Please try again.');
            }
        }
    });
    
    // Member notes functionality
    const memberNoteTextarea = document.getElementById('member-note');
    const saveNoteBtn = document.getElementById('save-note');
    const viewHistoryBtn = document.getElementById('view-history');
    
    // Save member note
    saveNoteBtn.addEventListener('click', async function() {
        const noteContent = memberNoteTextarea.value.trim();
        
        if (!noteContent) {
            alert('Please enter a note before saving.');
            return;
        }
        
        // Get the member's APEX ID from the user info (passed from template)
        const apexId = userApexId;
        
        if (!apexId || apexId === 'Unknown') {
            alert('Cannot save note: Member APEX ID not found.');
            return;
        }
        
        try {
            saveNoteBtn.disabled = true;
            saveNoteBtn.textContent = 'Saving...';
            
            const response = await fetch(`/api/members/${apexId}/notes`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Agent-ID': agentId,
                    'X-Agent-Name': agentName
                },
                body: JSON.stringify({
                    note: noteContent,
                    conversation_id: conversationId
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const result = await response.json();
            
            if (result.success) {
                // Clear the textarea
                memberNoteTextarea.value = '';
                
                // Show success message
                showNotification('Note saved to member profile successfully!', 'success');
            } else {
                throw new Error(result.error || 'Failed to save note');
            }
            
        } catch (error) {
            console.error('Error saving note:', error);
            showNotification('Error saving note: ' + error.message, 'error');
        } finally {
            saveNoteBtn.disabled = false;
            saveNoteBtn.textContent = 'Save Note to Profile';
        }
    });
    
    // Load conversation history automatically
    function scheduleHistoryRetry() {
        if (historyRetryAttempts >= maxHistoryRetries) {
            return false;
        }
        historyRetryAttempts += 1;
        setTimeout(() => loadConversationHistory({ force: true }), historyRetryDelayMs);
        return true;
    }

    async function loadConversationHistory(options = {}) {
        const force = Boolean(options.force);
        if ((historyLoaded && !force) || historyLoadInProgress) {
            return;
        }
        historyLoadInProgress = true;
        try {
            console.log(`[DEBUG] Fetching history for conversationId: ${conversationId}`);
            const url = `/api/conversations/${conversationId}/history`;
            console.log(`[DEBUG] Request URL: ${url}`);
            
            const response = await fetch(url);
            console.log(`[DEBUG] Response status: ${response.status}`);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const result = await response.json();
            console.log('[DEBUG] API Response:', result);
            
            if (result.success) {
                if (result.conversations.length === 0) {
                    if (scheduleHistoryRetry()) {
                        return;
                    }
                    console.warn('No conversation history found for this handoff');
                    addMessageToUI({
                        role: 'system',
                        content: '📋 No previous conversation history found',
                        timestamp: new Date().toISOString()
                    });
                    return;
                }
                
                // Find pre-handoff conversation
                console.log('[DEBUG] Looking for pre_handoff conversation in:', result.conversations);
                const preHandoffConversation = result.conversations.find(conv => conv.conversation_type === 'pre_handoff');
                console.log('[DEBUG] Found pre_handoff conversation:', preHandoffConversation);
                
                if (!preHandoffConversation || !preHandoffConversation.messages || preHandoffConversation.messages.length === 0) {
                    if (scheduleHistoryRetry()) {
                        return;
                    }
                    console.warn('Pre-handoff history is empty after retries');
                    addMessageToUI({
                        role: 'system',
                        content: '📋 No previous conversation history found',
                        timestamp: new Date().toISOString()
                    });
                    return;
                }

                if (preHandoffConversation && preHandoffConversation.messages && preHandoffConversation.messages.length > 0) {
                    historyLoaded = true;
                    historyRetryAttempts = 0;
                    // Auto-populate member notes with AI summary if available
                    if (preHandoffConversation.member_notes_summary) {
                        const memberNoteTextarea = document.getElementById('member-note');
                        if (memberNoteTextarea) {
                            memberNoteTextarea.value = preHandoffConversation.member_notes_summary;
                            console.log('[DEBUG] Auto-populated member notes with AI summary');
                        }
                    }
                    
                    // Add a system message indicating history is being loaded
                    addMessageToUI({
                        role: 'system',
                        content: `Loading ${preHandoffConversation.message_count} messages from conversation before handoff...`,
                        timestamp: new Date().toISOString()
                    });
                    
                // Add each historical message to the UI
                preHandoffConversation.messages.forEach(msg => {
                    addMessageToUI({
                        role: msg.role === 'Lucy' ? 'assistant' : msg.role.toLowerCase(),
                        content: msg.content,
                        timestamp: msg.timestamp,
                        isHistorical: true  // Mark as historical
                    });
                });

                // Safety net: confirm load without repeating raw markdown snippets.
                addMessageToUI({
                    role: 'system',
                    content: `Loaded ${preHandoffConversation.messages.length} pre-handoff messages. The transferred transcript above is rendered from Lucy's markdown-formatted conversation history.`,
                    timestamp: new Date().toISOString(),
                    isHistorical: false
                });
                    
                    // Add separator after historical messages
                    addMessageToUI({
                        role: 'system',
                        content: '━━━ Live conversation started ━━━',
                        timestamp: new Date().toISOString()
                    });
                    
                    scrollToBottom();
                }
            }
        } catch (error) {
            console.error('Error loading conversation history:', error);
            if (!scheduleHistoryRetry()) {
                addMessageToUI({
                    role: 'system',
                    content: '⚠️ Previous conversation history is currently unavailable',
                    timestamp: new Date().toISOString()
                });
            }
        } finally {
            historyLoadInProgress = false;
        }
    }
    
    // Reload conversation history
    viewHistoryBtn.addEventListener('click', async function() {
        try {
            viewHistoryBtn.disabled = true;
            viewHistoryBtn.innerHTML = '⏳ Loading...';
            
            // Clear any existing historical messages
            const historicalMessages = document.querySelectorAll('.message-wrapper.opacity-75');
            historicalMessages.forEach(msg => msg.remove());

            // Reload the conversation history
            historyLoaded = false;
            historyRetryAttempts = 0;
            await loadConversationHistory({ force: true });
            
            showNotification('History reloaded', 'success');
            
        } catch (error) {
            console.error('Error reloading history:', error);
            showNotification('Failed to reload history', 'error');
        } finally {
            viewHistoryBtn.disabled = false;
            viewHistoryBtn.innerHTML = '🔄 Reload History';
        }
    });
    
    // Show notification function
    function showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `fixed top-4 right-4 px-4 py-2 rounded-md text-white z-50 ${
            type === 'success' ? 'bg-green-600' :
            type === 'error' ? 'bg-red-600' :
            'bg-blue-600'
        }`;
        notification.textContent = message;
        
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.remove();
        }, 3000);
    }
    
    // Show history modal function
    function showHistoryModal(conversations) {
        const modal = document.createElement('div');
        modal.className = 'fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50';
        
        let historyContent = '';
        conversations.forEach(conv => {
            historyContent += `
                <div class="mb-4 p-3 border border-gray-200 rounded">
                    <h4 class="font-medium text-gray-900 mb-2">
                        ${conv.conversation_type === 'pre_handoff' ? 'Pre-Handoff Conversation' : 'Agent-Human Conversation'}
                    </h4>
                    <div class="text-sm text-gray-600 mb-2">
                        ${conv.message_count} messages • ${new Date(conv.created_at).toLocaleString()}
                    </div>
                    <div class="max-h-32 overflow-y-auto">
                        ${conv.messages.slice(0, 3).map(msg => `
                            <div class="text-xs mb-1">
                                <span class="font-medium">${escapeHtml(String(msg.role || 'message'))}:</span>
                                <span class="message-content">${renderMarkdown(String(msg.content || '').substring(0, 100))}${String(msg.content || '').length > 100 ? '...' : ''}</span>
                            </div>
                        `).join('')}
                        ${conv.messages.length > 3 ? '<div class="text-xs text-gray-500">... and more</div>' : ''}
                    </div>
                </div>
            `;
        });
        
        modal.innerHTML = `
            <div class="relative top-20 mx-auto p-5 border w-3/4 max-w-2xl shadow-lg rounded-md bg-white">
                <div class="mt-3">
                    <h3 class="text-lg font-medium text-gray-900 mb-4">Conversation History</h3>
                    <div class="max-h-96 overflow-y-auto">
                        ${historyContent}
                    </div>
                    <div class="flex justify-end mt-4">
                        <button onclick="this.closest('.fixed').remove()" class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50">
                            Close
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Close modal when clicking outside
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                modal.remove();
            }
        });
    }
    
    // Clean up on page unload
    window.addEventListener('beforeunload', function() {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.close();
        }
    });
}); 
