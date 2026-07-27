const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const ActivityStatus = require('../static/activity-status.js');

test('normalizes a working activity state', () => {
    assert.equal(ActivityStatus.normalize({ available: true, state: 'WORKING' }).state, 'WORKING');
});

test('shows unavailable agents as offline', () => {
    assert.equal(ActivityStatus.normalize({ available: false, state: 'DONE' }).displayState, 'OFFLINE');
});

test('limits recent activity to eight events', () => {
    assert.equal(
        ActivityStatus.normalize({ recent_events: new Array(20).fill({ kind: 'tool', text: 'Read chat' }) }).recentEvents.length,
        8,
    );
});

test('falls back to idle for an unknown state', () => {
    assert.equal(ActivityStatus.normalize({ available: true, state: 'mystery' }).state, 'IDLE');
});

test('adds event captions through textContent instead of HTML', () => {
    const textNodes = [];
    const document = {
        createElement() {
            const node = {
                className: '',
                children: [],
                appendChild(child) { this.children.push(child); },
            };
            Object.defineProperty(node, 'textContent', {
                set(value) { textNodes.push(value); },
            });
            return node;
        },
    };
    const container = { replaceChildren(...children) { this.children = children; } };
    const caption = '<img src=x onerror=alert(1)>';

    ActivityStatus.renderRecentEvents(document, container, [{ time: 0, text: caption }]);

    assert.ok(textNodes.includes(caption));
    assert.equal(textNodes.some(value => value.includes('&lt;img')), false);
});

test('loads the activity helper before the chat client', () => {
    const page = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
    assert.ok(page.indexOf('/static/activity-status.js') > -1);
    assert.ok(page.indexOf('/static/activity-status.js') < page.indexOf('/static/chat.js'));
});

test('chat status handling renders lifecycle labels and recent activity', () => {
    const chat = fs.readFileSync(path.join(__dirname, '../static/chat.js'), 'utf8');
    assert.match(chat, /ActivityStatus\.normalize\(info\)/);
    assert.match(chat, /ActivityStatus\.renderRecentEvents/);
    assert.match(chat, /status-state/);
});

test('styles each lifecycle label and the read-only activity feed', () => {
    const styles = fs.readFileSync(path.join(__dirname, '../static/style.css'), 'utf8');
    for (const state of ['waiting', 'working', 'blocked', 'done', 'idle', 'offline']) {
        assert.match(styles, new RegExp(`status-state\\.state-${state}`));
    }
    assert.match(styles, /pill-activity-events/);
    assert.match(styles, /activity-event-caption/);
});
