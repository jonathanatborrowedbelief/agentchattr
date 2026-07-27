/* agentchattr — safe activity-status presentation helpers */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    root.ActivityStatus = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
    const STATES = new Set(['WAITING', 'WORKING', 'BLOCKED', 'DONE', 'IDLE']);
    const MAX_RECENT_EVENTS = 8;

    function normalize(info = {}) {
        const state = String(info.state || 'IDLE').toUpperCase();
        const recentEvents = Array.isArray(info.recent_events)
            ? info.recent_events.slice(-MAX_RECENT_EVENTS)
            : [];
        const normalizedState = STATES.has(state) ? state : 'IDLE';

        return {
            state: normalizedState,
            displayState: info.available === false ? 'OFFLINE' : normalizedState,
            event: info.event && typeof info.event === 'object' ? info.event : null,
            recentEvents,
        };
    }

    function eventCaption(event = {}) {
        return typeof event.text === 'string' ? event.text : '';
    }

    function formatTimestamp(value) {
        const timestamp = typeof value === 'number' ? value * 1000 : Date.parse(value);
        if (!Number.isFinite(timestamp)) return '';
        return new Date(timestamp).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }

    function renderRecentEvents(document, container, events) {
        const fragment = document.createElement('div');
        fragment.className = 'activity-events';
        const visibleEvents = Array.isArray(events) ? events.slice(-MAX_RECENT_EVENTS) : [];

        if (visibleEvents.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'activity-events-empty';
            empty.textContent = 'No recent activity';
            fragment.appendChild(empty);
        } else {
            for (const event of visibleEvents) {
                const row = document.createElement('div');
                row.className = 'activity-event';
                const time = document.createElement('time');
                time.className = 'activity-event-time';
                time.textContent = formatTimestamp(event.time);
                const caption = document.createElement('span');
                caption.className = 'activity-event-caption';
                caption.textContent = eventCaption(event);
                row.appendChild(time);
                row.appendChild(caption);
                fragment.appendChild(row);
            }
        }

        container.replaceChildren(fragment);
    }

    return { normalize, eventCaption, formatTimestamp, renderRecentEvents };
});
