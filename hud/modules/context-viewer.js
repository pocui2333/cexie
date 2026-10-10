/**
 * 侧写 (Cexie) - 对话上下文展示模块 (ContextViewer)
 * 职责：
 * 1. 独立管理对方最新消息、我方最新回复、发送者、消息时间及回复状态标识；
 * 2. 严格遵循各 DOM 节点独立容错更新原则，杜绝节点耦合导致渲染中断；
 * 3. 内置数据脏检查 (Dirty-Diffing)，避免无谓的 DOM 重绘。
 */

class ContextViewer {
    constructor(windowManager) {
        this.windowManager = windowManager;

        // 缓存 DOM 节点引用
        this.targetSenderName = document.getElementById('target-sender-name');
        this.targetMessageTime = document.getElementById('target-message-time');
        this.incomingMessageBox = document.getElementById('incoming-message-box');
        this.egoMessageBox = document.getElementById('ego-message-box');
        this.egoStatusBadge = document.getElementById('ego-status-badge');
        this.egoStatusDot = document.getElementById('ego-status-dot');

        // 脏检查缓存
        this.lastIncomingText = null;
        this.lastEgoText = null;
        this.lastReplyStatus = null;
        this.lastSenderName = null;
        this.lastMessageTime = null;
    }

    /**
     * 更新上下文数据
     * @param {Object} data - /api/poll 返回的上下文数据切片
     */
    update(data) {
        if (!data) return;

        // 1. 发送者名称更新 (独立容错)
        const senderName = data.sender_name || data.target;
        if (senderName && senderName !== this.lastSenderName) {
            this.lastSenderName = senderName;
            if (this.targetSenderName) {
                this.targetSenderName.textContent = senderName;
            }
        }

        // 2. 消息时间更新 (独立容错)
        const msgTime = data.message_time || '刚刚';
        if (msgTime !== this.lastMessageTime) {
            this.lastMessageTime = msgTime;
            if (this.targetMessageTime) {
                this.targetMessageTime.textContent = msgTime;
            }
        }

        // 3. 对方消息更新 (独立容错 + 脏检查)
        if (data.incoming_text && data.incoming_text !== this.lastIncomingText) {
            this.lastIncomingText = data.incoming_text;
            if (this.incomingMessageBox) {
                this.incomingMessageBox.textContent = data.incoming_text;
            }
            if (this.windowManager && typeof this.windowManager.fitWindowToContent === 'function') {
                this.windowManager.fitWindowToContent();
            }
        }

        // 4. 我方最新回复更新 (独立容错 + 脏检查：在对方最后一条消息之后，展示我方的所有发言)
        const hasEgoMessages = Boolean(data.ego_text && data.ego_text.trim().length > 0 && data.ego_text !== '暂未回复');
        const isReplied = data.reply_status === 'replied' && hasEgoMessages;
        let currentEgoText = '无（暂未回复）';
        if (hasEgoMessages) {
            currentEgoText = data.ego_text;
        }

        const currentStatus = isReplied ? 'replied' : 'pending';

        if (currentEgoText !== this.lastEgoText || currentStatus !== this.lastReplyStatus) {
            this.lastEgoText = currentEgoText;
            this.lastReplyStatus = currentStatus;

            // 更新消息文本框 (单独执行，绝不与其他元素耦合)
            if (this.egoMessageBox) {
                this.egoMessageBox.textContent = currentEgoText;
                if (data.ego_text && data.ego_text !== '暂未回复' && data.ego_text.trim().length > 0) {
                    this.egoMessageBox.className = 'ego-box';
                } else if (isReplied) {
                    this.egoMessageBox.className = 'ego-box';
                } else {
                    this.egoMessageBox.className = 'ego-box pending-state';
                }
            }

            // 更新状态胶囊徽章 (单独执行)
            if (this.egoStatusBadge) {
                if (isReplied) {
                    this.egoStatusBadge.textContent = '已回复';
                    this.egoStatusBadge.className = 'status-badge badge-replied';
                } else {
                    this.egoStatusBadge.textContent = '待我回复';
                    this.egoStatusBadge.className = 'status-badge badge-pending';
                }
            }

            // 更新状态圆点指示灯 (单独执行)
            if (this.egoStatusDot) {
                if (isReplied) {
                    this.egoStatusDot.className = 'status-dot ego-dot replied';
                } else {
                    this.egoStatusDot.className = 'status-dot ego-dot';
                }
            }

            if (this.windowManager && typeof this.windowManager.fitWindowToContent === 'function') {
                this.windowManager.fitWindowToContent();
            }
        }
    }

    /**
     * 显示窗口不匹配安全阻断提示
     */
    showMismatchAlert(detected, target) {
        if (!this.incomingMessageBox) return;
        const originalText = this.lastIncomingText || this.incomingMessageBox.textContent;
        this.incomingMessageBox.innerHTML = `<span style="color:#f87171;font-weight:600;">【安全阻断】当前微信停留在「${escapeHtml(detected)}」，非目标「${escapeHtml(target)}」！<br>请在微信中切换至目标聊天窗口后再点击抓取。</span>`;
        setTimeout(() => {
            if (this.incomingMessageBox && this.incomingMessageBox.innerHTML.includes('【安全阻断】')) {
                this.incomingMessageBox.textContent = originalText;
            }
        }, 3200);
    }
}

window.ContextViewer = ContextViewer;
