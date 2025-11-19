/**
 * BROCKSTON Studio Frontend Application
 *
 * Handles Monaco Editor integration, file operations, and BROCKSTON interactions.
 */

// Global state
const state = {
    editor: null,
    currentFilePath: null,
    proposedCode: null,
    chatHistory: [],
};

// DOM elements
const elements = {
    filePathInput: null,
    btnOpen: null,
    btnSave: null,
    btnAsk: null,
    btnSuggest: null,
    btnClearChat: null,
    currentFileSpan: null,
    chatLog: null,
    instructionInput: null,
    comparisonModal: null,
    btnCloseModal: null,
    btnApply: null,
    btnReject: null,
    currentCodePre: null,
    proposedCodePre: null,
    comparisonSummary: null,
    loadingOverlay: null,
    workspaceInfo: null,
    // Git modal elements
    btnGit: null,
    gitModal: null,
    btnCloseGitModal: null,
    btnCancelClone: null,
    btnCloneRepo: null,
    gitUrl: null,
    folderName: null,
    gitStatusMessage: null,
};

// Initialize application
function init() {
    // Get DOM elements
    elements.filePathInput = document.getElementById('file-path');
    elements.btnOpen = document.getElementById('btn-open');
    elements.btnSave = document.getElementById('btn-save');
    elements.btnAsk = document.getElementById('btn-ask');
    elements.btnSuggest = document.getElementById('btn-suggest');
    elements.btnClearChat = document.getElementById('btn-clear-chat');
    elements.currentFileSpan = document.getElementById('current-file');
    elements.chatLog = document.getElementById('chat-log');
    elements.instructionInput = document.getElementById('instruction-input');
    elements.comparisonModal = document.getElementById('comparison-modal');
    elements.btnCloseModal = document.getElementById('btn-close-modal');
    elements.btnApply = document.getElementById('btn-apply');
    elements.btnReject = document.getElementById('btn-reject');
    elements.currentCodePre = document.getElementById('current-code');
    elements.proposedCodePre = document.getElementById('proposed-code');
    elements.comparisonSummary = document.getElementById('comparison-summary');
    elements.loadingOverlay = document.getElementById('loading-overlay');
    elements.workspaceInfo = document.getElementById('workspace-info');
    // Git modal elements
    elements.btnGit = document.getElementById('btn-git');
    elements.gitModal = document.getElementById('git-modal');
    elements.btnCloseGitModal = document.getElementById('btn-close-git-modal');
    elements.btnCancelClone = document.getElementById('btn-cancel-clone');
    elements.btnCloneRepo = document.getElementById('btn-clone-repo');
    elements.gitUrl = document.getElementById('git-url');
    elements.folderName = document.getElementById('folder-name');
    elements.gitStatusMessage = document.getElementById('git-status-message');

    // Initialize Monaco Editor
    initMonacoEditor();

    // Attach event listeners
    attachEventListeners();

    // Load workspace info
    loadWorkspaceInfo();
}

// Initialize Monaco Editor
function initMonacoEditor() {
    require(['vs/editor/editor.main'], function () {
        state.editor = monaco.editor.create(document.getElementById('monaco-editor'), {
            value: '// Open a file to start editing...\n',
            language: 'javascript',
            theme: 'vs-dark',
            automaticLayout: true,
            minimap: { enabled: true },
            fontSize: 14,
            tabSize: 4,
            wordWrap: 'on',
        });

        console.log('Monaco Editor initialized');
    });
}

// Attach event listeners
function attachEventListeners() {
    elements.btnOpen.addEventListener('click', handleOpenFile);
    elements.btnSave.addEventListener('click', handleSaveFile);
    elements.btnAsk.addEventListener('click', handleAskBrockston);
    elements.btnSuggest.addEventListener('click', handleSuggestFix);
    elements.btnClearChat.addEventListener('click', handleClearChat);
    elements.btnCloseModal.addEventListener('click', closeComparisonModal);
    elements.btnReject.addEventListener('click', closeComparisonModal);
    elements.btnApply.addEventListener('click', handleApplyChanges);

    // Git modal event listeners
    elements.btnGit.addEventListener('click', openGitModal);
    elements.btnCloseGitModal.addEventListener('click', closeGitModal);
    elements.btnCancelClone.addEventListener('click', closeGitModal);
    elements.btnCloneRepo.addEventListener('click', handleCloneRepo);

    // Enter key in file path opens file
    elements.filePathInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            handleOpenFile();
        }
    });

    // Ctrl+S to save
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            if (!elements.btnSave.disabled) {
                handleSaveFile();
            }
        }
    });
}

// Load workspace info
async function loadWorkspaceInfo() {
    try {
        const response = await fetch('/health');
        const data = await response.json();
        if (data.workspace) {
            elements.workspaceInfo.textContent = `Workspace: ${data.workspace}`;
        }
    } catch (error) {
        console.error('Failed to load workspace info:', error);
    }
}

// Handle opening a file
async function handleOpenFile() {
    const path = elements.filePathInput.value.trim();
    if (!path) {
        showError('Please enter a file path');
        return;
    }

    showLoading();

    try {
        const response = await fetch(`/api/files/open?path=${encodeURIComponent(path)}`);

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to open file');
        }

        const data = await response.json();

        // Update editor
        state.editor.setValue(data.content);
        state.currentFilePath = data.path;

        // Detect and set language
        const language = detectLanguage(data.path);
        monaco.editor.setModelLanguage(state.editor.getModel(), language);

        // Update UI
        elements.currentFileSpan.textContent = data.path;
        elements.btnSave.disabled = false;
        elements.btnAsk.disabled = false;
        elements.btnSuggest.disabled = false;

        addChatMessage('system', `File opened: ${data.path}`);

    } catch (error) {
        showError(`Failed to open file: ${error.message}`);
    } finally {
        hideLoading();
    }
}

// Handle saving a file
async function handleSaveFile() {
    if (!state.currentFilePath) {
        showError('No file open');
        return;
    }

    showLoading();

    try {
        const content = state.editor.getValue();

        const response = await fetch('/api/files/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                path: state.currentFilePath,
                content: content,
            }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to save file');
        }

        const data = await response.json();
        addChatMessage('system', `File saved: ${data.path}`);

    } catch (error) {
        showError(`Failed to save file: ${error.message}`);
    } finally {
        hideLoading();
    }
}

// Handle asking BROCKSTON a question
async function handleAskBrockston() {
    const instruction = elements.instructionInput.value.trim();
    if (!instruction) {
        showError('Please enter a question or instruction');
        return;
    }

    if (!state.currentFilePath) {
        showError('Please open a file first');
        return;
    }

    showLoading();

    try {
        const code = state.editor.getValue();

        // Build message history
        const messages = [
            {
                role: 'system',
                content: 'You are BROCKSTON, a reasoning engine that helps developers understand and improve their code. Be concise, precise, and helpful.',
            },
            {
                role: 'user',
                content: instruction,
            },
        ];

        const response = await fetch('/api/brockston/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                messages: messages,
                context: {
                    path: state.currentFilePath,
                    code: code,
                },
            }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to communicate with BROCKSTON');
        }

        const data = await response.json();

        // Add to chat log
        addChatMessage('user', instruction);
        addChatMessage('assistant', data.reply);

        // Clear instruction input
        elements.instructionInput.value = '';

    } catch (error) {
        showError(`BROCKSTON error: ${error.message}`);
    } finally {
        hideLoading();
    }
}

// Handle requesting code suggestions
async function handleSuggestFix() {
    const instruction = elements.instructionInput.value.trim();
    if (!instruction) {
        showError('Please enter an instruction (e.g., "refactor for clarity")');
        return;
    }

    if (!state.currentFilePath) {
        showError('Please open a file first');
        return;
    }

    showLoading();

    try {
        const code = state.editor.getValue();

        const response = await fetch('/api/brockston/suggest_fix', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                instruction: instruction,
                path: state.currentFilePath,
                code: code,
            }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to get suggestions from BROCKSTON');
        }

        const data = await response.json();

        // Store proposed code
        state.proposedCode = data.proposed_code;

        // Show comparison modal
        showComparisonModal(code, data.proposed_code, data.summary);

        // Add to chat log
        addChatMessage('user', `Suggest fix: ${instruction}`);
        addChatMessage('assistant', `Proposed changes: ${data.summary}`);

        // Clear instruction input
        elements.instructionInput.value = '';

    } catch (error) {
        showError(`BROCKSTON error: ${error.message}`);
    } finally {
        hideLoading();
    }
}

// Show comparison modal
function showComparisonModal(currentCode, proposedCode, summary) {
    elements.currentCodePre.textContent = currentCode;
    elements.proposedCodePre.textContent = proposedCode;
    elements.comparisonSummary.textContent = summary;
    elements.comparisonModal.classList.add('active');
}

// Close comparison modal
function closeComparisonModal() {
    elements.comparisonModal.classList.remove('active');
    state.proposedCode = null;
}

// Handle applying proposed changes
function handleApplyChanges() {
    if (state.proposedCode) {
        state.editor.setValue(state.proposedCode);
        addChatMessage('system', 'Proposed changes applied to editor. Remember to save!');
        closeComparisonModal();
    }
}

// Handle clearing chat log
function handleClearChat() {
    elements.chatLog.innerHTML = `
        <div class="chat-message system">
            <strong>BROCKSTON:</strong> Chat cleared. Ready for new questions.
        </div>
    `;
    state.chatHistory = [];
}

// Add message to chat log
function addChatMessage(role, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${role}`;

    let roleLabel = 'BROCKSTON';
    if (role === 'user') roleLabel = 'You';
    else if (role === 'system') roleLabel = 'System';

    const contentHtml = content.replace(/\n/g, '<br>');

    messageDiv.innerHTML = `
        <strong>${roleLabel}:</strong>
        ${contentHtml}
    `;

    elements.chatLog.appendChild(messageDiv);
    elements.chatLog.scrollTop = elements.chatLog.scrollHeight;

    state.chatHistory.push({ role, content });
}

// Detect programming language from file extension
function detectLanguage(filePath) {
    const ext = filePath.split('.').pop().toLowerCase();
    const languageMap = {
        'js': 'javascript',
        'ts': 'typescript',
        'jsx': 'javascript',
        'tsx': 'typescript',
        'py': 'python',
        'java': 'java',
        'c': 'c',
        'cpp': 'cpp',
        'cs': 'csharp',
        'go': 'go',
        'rs': 'rust',
        'rb': 'ruby',
        'php': 'php',
        'swift': 'swift',
        'kt': 'kotlin',
        'html': 'html',
        'css': 'css',
        'scss': 'scss',
        'json': 'json',
        'xml': 'xml',
        'yaml': 'yaml',
        'yml': 'yaml',
        'md': 'markdown',
        'sh': 'shell',
        'bash': 'shell',
        'sql': 'sql',
    };

    return languageMap[ext] || 'plaintext';
}

// Show loading overlay
function showLoading() {
    elements.loadingOverlay.classList.add('active');
}

// Hide loading overlay
function hideLoading() {
    elements.loadingOverlay.classList.remove('active');
}

// Show error message
function showError(message) {
    addChatMessage('system', `ERROR: ${message}`);
}

// ============================================================================
// Git Operations
// ============================================================================

// Open Git modal
function openGitModal() {
    elements.gitModal.classList.add('active');
    elements.gitUrl.value = '';
    elements.folderName.value = '';
    elements.gitStatusMessage.textContent = '';
    elements.gitStatusMessage.className = 'git-status-message';
}

// Close Git modal
function closeGitModal() {
    elements.gitModal.classList.remove('active');
    elements.gitUrl.value = '';
    elements.folderName.value = '';
    elements.gitStatusMessage.textContent = '';
}

// Handle cloning a repository
async function handleCloneRepo() {
    const gitUrl = elements.gitUrl.value.trim();
    const folderName = elements.folderName.value.trim() || null;

    // Validate URL
    if (!gitUrl) {
        showGitStatus('Please enter a repository URL', 'error');
        return;
    }

    if (!gitUrl.startsWith('https://')) {
        showGitStatus('Please use an HTTPS URL (e.g., https://github.com/...)', 'error');
        return;
    }

    // Disable button during clone
    elements.btnCloneRepo.disabled = true;
    elements.btnCloneRepo.textContent = 'Cloning...';
    showGitStatus('Cloning repository, please wait...', 'info');

    try {
        const response = await fetch('/api/git/clone', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                git_url: gitUrl,
                folder_name: folderName,
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to clone repository');
        }

        // Success! Update UI with cloned repo path
        showGitStatus(`✓ Successfully cloned to: ${data.local_path}`, 'success');
        addChatMessage('system', `Repository cloned: ${data.workspace_name} at ${data.local_path}`);

        // Pre-fill the file path input with the cloned repo path
        elements.filePathInput.value = `${data.local_path}/`;

        // Close modal after a short delay
        setTimeout(() => {
            closeGitModal();
        }, 2000);

    } catch (error) {
        showGitStatus(`✗ Clone failed: ${error.message}`, 'error');
        console.error('Clone error:', error);
    } finally {
        elements.btnCloneRepo.disabled = false;
        elements.btnCloneRepo.textContent = 'Clone & Open';
    }
}

// Show status message in Git modal
function showGitStatus(message, type) {
    elements.gitStatusMessage.textContent = message;
    elements.gitStatusMessage.className = `git-status-message ${type}`;
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
