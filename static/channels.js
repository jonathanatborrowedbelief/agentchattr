// channels.js -- Channel tabs, switching, filtering, CRUD
// Extracted from chat.js PR 4.  Reads shared state via window.* bridges.

'use strict';

// ---------------------------------------------------------------------------
// State (local to channels)
// ---------------------------------------------------------------------------

const _channelScrollMsg = {};  // channel name -> message ID at top of viewport
const _protectedOperationalChannels = new Set(['video-lab', 'publish-queue']);

function _userCreatedChannelCount() {
    return (window.channelList || []).filter(name =>
        name !== 'general' && !_protectedOperationalChannels.has(name)
    ).length;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _getTopVisibleMsgId() {
    const scroll = document.getElementById('timeline');
    const container = document.getElementById('messages');
    if (!scroll || !container) return null;
    const rect = scroll.getBoundingClientRect();
    for (const el of container.children) {
        if (el.style.display === 'none' || !el.dataset.id) continue;
        const elRect = el.getBoundingClientRect();
        if (elRect.bottom > rect.top) return el.dataset.id;
    }
    return null;
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function renderChannelTabs() {
    // Render into sidebar
    const sidebar = document.getElementById('channel-sidebar-list');
    if (sidebar) _renderChannelSidebar(sidebar);

    // Also render legacy top bar for compatibility
    const container = document.getElementById('channel-tabs');
    if (container) {
        container.innerHTML = '';
        for (const name of window.channelList) {
            const tab = document.createElement('button');
            tab.className = 'channel-tab' + (name === window.activeChannel ? ' active' : '');
            tab.dataset.channel = name;
            const label = document.createElement('span');
            label.className = 'channel-tab-label';
            label.textContent = '# ' + name;
            tab.appendChild(label);
            tab.onclick = () => switchChannel(name);
            container.appendChild(tab);
        }
    }

    // Update add button disabled state
    const addBtn = document.getElementById('channel-sidebar-add');
    if (addBtn) {
        addBtn.classList.toggle('disabled', _userCreatedChannelCount() >= 8);
    }
}

function _renderChannelSidebar(container) {
    // Preserve inline create if open
    const existingCreate = container.querySelector('.channel-sidebar-create');
    container.innerHTML = '';

    for (const name of window.channelList) {
        const item = document.createElement('div');
        item.className = 'channel-sidebar-item' + (name === window.activeChannel ? ' active' : '');
        item.dataset.channel = name;

        const hash = document.createElement('span');
        hash.className = 'channel-hash';
        hash.textContent = '#';
        item.appendChild(hash);

        const label = document.createElement('span');
        label.className = 'channel-sidebar-name';
        label.textContent = name;
        item.appendChild(label);

        const unread = window.channelUnread[name] || 0;
        if (unread > 0 && name !== window.activeChannel) {
            const badge = document.createElement('span');
            badge.className = 'channel-sidebar-unread';
            badge.textContent = unread > 99 ? '99+' : unread;
            item.appendChild(badge);
        }

        // Operational channels are persistent workflow destinations.
        if (name !== 'general' && !_protectedOperationalChannels.has(name)) {
            const actions = document.createElement('span');
            actions.className = 'channel-sidebar-actions';

            const editBtn = document.createElement('button');
            editBtn.className = 'ch-edit-btn';
            editBtn.title = 'Rename';
            editBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 16 16" fill="none"><path d="M11.5 2.5l2 2L5 13H3v-2L11.5 2.5z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>';
            editBtn.onclick = (e) => { e.stopPropagation(); showChannelRenameDialog(name); };
            actions.appendChild(editBtn);

            const delBtn = document.createElement('button');
            delBtn.className = 'ch-delete-btn';
            delBtn.title = 'Delete';
            delBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 16 16" fill="none"><path d="M3 4h10M6 4V3h4v1M5 4v8.5h6V4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
            delBtn.onclick = (e) => { e.stopPropagation(); deleteChannel(name); };
            actions.appendChild(delBtn);

            item.appendChild(actions);
        }

        item.onclick = (e) => {
            if (e.target.closest('.channel-sidebar-actions')) return;
            if (e.target.closest('.channel-session-end')) return;
            switchChannel(name);
        };

        container.appendChild(item);

        // Show session indicator if a session is active on this channel
        if (typeof window.getActiveSessionForChannel === 'function') {
            const session = window.getActiveSessionForChannel(name);
            if (session) {
                const sessionRow = document.createElement('div');
                sessionRow.className = 'channel-sidebar-session';
                const sessionLabel = document.createElement('span');
                sessionLabel.className = 'channel-sidebar-session-label';
                const stateLabel = session.state === 'waiting_for_cast' ? ' — waiting for shared cast' : '';
                sessionLabel.textContent = (session.template_name || 'Session') + stateLabel;
                sessionRow.appendChild(sessionLabel);
                const endBtn = document.createElement('button');
                endBtn.className = 'channel-session-end';
                endBtn.textContent = 'End';
                endBtn.title = 'End session on #' + name;
                endBtn.onclick = (e) => {
                    e.stopPropagation();
                    if (endBtn.dataset.confirming) {
                        window.endSessionForChannel(name);
                        endBtn.dataset.confirming = '';
                        endBtn.textContent = 'End';
                        return;
                    }
                    endBtn.dataset.confirming = '1';
                    endBtn.textContent = 'Confirm?';
                    setTimeout(() => {
                        if (endBtn.dataset.confirming) {
                            endBtn.dataset.confirming = '';
                            endBtn.textContent = 'End';
                        }
                    }, 3000);
                };
                sessionRow.appendChild(endBtn);
                container.appendChild(sessionRow);
            }
        }
    }

    // Re-append inline create if open
    if (existingCreate) {
        container.appendChild(existingCreate);
    }
}

// ---------------------------------------------------------------------------
// Switch / filter
// ---------------------------------------------------------------------------

function switchChannel(name) {
    if (name === window.activeChannel) return;
    // Save top-visible message ID for current channel
    const topId = _getTopVisibleMsgId();
    if (topId) _channelScrollMsg[window.activeChannel] = topId;
    window._setActiveChannel(name);
    window.channelUnread[name] = 0;
    localStorage.setItem('agentchattr-channel', name);
    filterMessagesByChannel();
    renderChannelTabs();
    Store.set('activeChannel', name);
    // Restore: scroll to saved message, or bottom if none saved
    const savedId = _channelScrollMsg[name];
    if (savedId) {
        const el = document.querySelector(`.message[data-id="${savedId}"]`);
        if (el) { el.scrollIntoView({ block: 'start' }); return; }
    }
    window.scrollToBottom();
}

function filterMessagesByChannel() {
    const container = document.getElementById('messages');
    if (!container) return;

    for (const el of container.children) {
        const ch = el.dataset.channel || 'general';
        el.style.display = ch === window.activeChannel ? '' : 'none';
    }
}

// ---------------------------------------------------------------------------
// Create
// ---------------------------------------------------------------------------

function showChannelCreateDialog() {
    if (_userCreatedChannelCount() >= 8) return;

    // Use sidebar list as the target
    const list = document.getElementById('channel-sidebar-list');
    if (!list) return;

    // Remove existing inline create if any
    list.querySelector('.channel-sidebar-create')?.remove();

    const addBtn = document.getElementById('channel-sidebar-add');
    if (addBtn) addBtn.style.display = 'none';

    const wrapper = document.createElement('div');
    wrapper.className = 'channel-sidebar-create';

    const prefix = document.createElement('span');
    prefix.className = 'channel-hash';
    prefix.textContent = '#';
    prefix.style.color = 'var(--text-dim)';
    wrapper.appendChild(prefix);

    const input = document.createElement('input');
    input.type = 'text';
    input.maxLength = 20;
    input.placeholder = 'channel-name';
    wrapper.appendChild(input);

    const cleanup = () => { wrapper.remove(); if (addBtn) addBtn.style.display = ''; };

    const confirm = document.createElement('button');
    confirm.className = 'confirm-btn';
    confirm.innerHTML = '&#10003;';
    confirm.title = 'Create';
    confirm.onclick = () => { _submitInlineCreate(input, wrapper); if (addBtn) addBtn.style.display = ''; };
    wrapper.appendChild(confirm);

    const cancel = document.createElement('button');
    cancel.className = 'cancel-btn';
    cancel.innerHTML = '&#10005;';
    cancel.title = 'Cancel';
    cancel.onclick = cleanup;
    wrapper.appendChild(cancel);

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); _submitInlineCreate(input, wrapper); if (addBtn) addBtn.style.display = ''; }
        if (e.key === 'Escape') cleanup();
    });
    input.addEventListener('input', () => {
        input.value = input.value.toLowerCase().replace(/[^a-z0-9\-]/g, '');
    });

    list.appendChild(wrapper);
    input.focus();
}

function _submitInlineCreate(input, wrapper) {
    const name = input.value.trim().toLowerCase();
    if (!name || !/^[a-z0-9][a-z0-9\-]{0,19}$/.test(name)) return;
    if (window.channelList.includes(name)) { input.focus(); return; }
    window._setPendingChannelSwitch(name);
    window.ws.send(JSON.stringify({ type: 'channel_create', name }));
    wrapper.remove();
}

// ---------------------------------------------------------------------------
// Rename
// ---------------------------------------------------------------------------

function showChannelRenameDialog(oldName) {
    if (_protectedOperationalChannels.has(oldName)) return;
    const list = document.getElementById('channel-sidebar-list');
    if (!list) return;
    list.querySelector('.channel-sidebar-create')?.remove();

    // Find the sidebar item being renamed
    const targetItem = list.querySelector(`.channel-sidebar-item[data-channel="${oldName}"]`);

    const wrapper = document.createElement('div');
    wrapper.className = 'channel-sidebar-create';

    const prefix = document.createElement('span');
    prefix.className = 'channel-hash';
    prefix.textContent = '#';
    prefix.style.color = 'var(--text-dim)';
    wrapper.appendChild(prefix);

    const input = document.createElement('input');
    input.type = 'text';
    input.maxLength = 20;
    input.value = oldName;
    wrapper.appendChild(input);

    const cleanup = () => {
        wrapper.remove();
        if (targetItem) targetItem.style.display = '';
    };

    const confirm = document.createElement('button');
    confirm.className = 'confirm-btn';
    confirm.innerHTML = '&#10003;';
    confirm.title = 'Rename';
    confirm.onclick = () => {
        const newName = input.value.trim().toLowerCase();
        if (!newName || !/^[a-z0-9][a-z0-9\-]{0,19}$/.test(newName)) return;
        if (newName !== oldName) {
            window.ws.send(JSON.stringify({ type: 'channel_rename', old_name: oldName, new_name: newName }));
            if (window.activeChannel === oldName) {
                window._setActiveChannel(newName);
                localStorage.setItem('agentchattr-channel', newName);
                Store.set('activeChannel', newName);
            }
        }
        cleanup();
    };
    wrapper.appendChild(confirm);

    const cancel = document.createElement('button');
    cancel.className = 'cancel-btn';
    cancel.innerHTML = '&#10005;';
    cancel.title = 'Cancel';
    cancel.onclick = cleanup;
    wrapper.appendChild(cancel);

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); confirm.click(); }
        if (e.key === 'Escape') cleanup();
    });
    input.addEventListener('input', () => {
        input.value = input.value.toLowerCase().replace(/[^a-z0-9\-]/g, '');
    });

    // Insert inline next to the item, hide the original
    if (targetItem) {
        targetItem.style.display = 'none';
        targetItem.insertAdjacentElement('afterend', wrapper);
    } else {
        list.appendChild(wrapper);
    }
    input.select();
}

// ---------------------------------------------------------------------------
// Delete
// ---------------------------------------------------------------------------

function deleteChannel(name) {
    if (name === 'general' || _protectedOperationalChannels.has(name)) return;
    // Try sidebar item first, fall back to tab
    const item = document.querySelector(`.channel-sidebar-item[data-channel="${name}"]`)
              || document.querySelector(`.channel-tab[data-channel="${name}"]`);
    if (!item || item.classList.contains('confirm-delete')) return;

    const label = item.querySelector('.channel-sidebar-name') || item.querySelector('.channel-tab-label');
    const actions = item.querySelector('.channel-sidebar-actions') || item.querySelector('.channel-tab-actions');
    const originalText = label.textContent;
    const originalOnclick = item.onclick;

    item.classList.add('confirm-delete');
    label.textContent = `delete?`;
    label.style.color = 'var(--error-color)';
    if (actions) actions.style.display = 'none';

    const confirmBar = document.createElement('span');
    confirmBar.className = 'channel-delete-confirm';
    confirmBar.style.marginLeft = 'auto';

    const tickBtn = document.createElement('button');
    tickBtn.className = 'ch-confirm-yes';
    tickBtn.title = 'Confirm delete';
    tickBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M3 8.5l3.5 3.5 6.5-7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

    const crossBtn = document.createElement('button');
    crossBtn.className = 'ch-confirm-no';
    crossBtn.title = 'Cancel';
    crossBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

    confirmBar.appendChild(tickBtn);
    confirmBar.appendChild(crossBtn);
    item.appendChild(confirmBar);

    const revert = () => {
        item.classList.remove('confirm-delete');
        label.textContent = originalText;
        label.style.color = '';
        if (actions) actions.style.display = '';
        confirmBar.remove();
        item.onclick = originalOnclick;
        document.removeEventListener('click', outsideClick);
    };

    tickBtn.onclick = (e) => {
        e.stopPropagation();
        revert();
        window.ws.send(JSON.stringify({ type: 'channel_delete', name }));
        if (window.activeChannel === name) switchChannel('general');
    };

    crossBtn.onclick = (e) => {
        e.stopPropagation();
        revert();
    };

    item.onclick = (e) => { e.stopPropagation(); };

    const outsideClick = (e) => {
        if (!item.contains(e.target)) revert();
    };
    setTimeout(() => document.addEventListener('click', outsideClick), 0);
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

function _channelsInit() {
    // Nothing to do yet -- channel rendering is driven by chat.js calling
    // renderChannelTabs() and filterMessagesByChannel() at the right times.
}

// ---------------------------------------------------------------------------
// Window exports (for inline onclick in index.html and chat.js callers)
// ---------------------------------------------------------------------------

window.showChannelCreateDialog = showChannelCreateDialog;
window.switchChannel = switchChannel;
window.filterMessagesByChannel = filterMessagesByChannel;
window.renderChannelTabs = renderChannelTabs;
window.deleteChannel = deleteChannel;
window.showChannelRenameDialog = showChannelRenameDialog;
window.Channels = { init: _channelsInit };
