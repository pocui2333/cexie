/**
 * 侧写 (Cexie) - HUD 交互引擎与数据协同控制器
 * 
 * 核心架构准则：
 * 1. 纯视图呈现：完全通过 /api/poll 与 /api/trigger 获取后端单源数据并渲染；
 * 2. 脏检查机制 (Dirty-Diffing)：数据不变时绝不触碰或重构 DOM，杜绝闪烁与布局震荡；
 * 3. 尺寸收敛防抖：高度按内容自适应，窗口调整严格收敛，严禁高频向系统发起无谓 resize；
 * 4. 极速响应：点击即复制（含视觉反馈），抓取按钮 500ms 安全防重防抖。
 */

class EchoLensHUD {
    constructor() {
        this.activeTarget = '';
        this.isCollapsed = false;
        this.currentView = 'monitor'; // 'monitor' | 'ingest'
        this.pollTimer = null;
        this.isCapturing = false;
        this.lastCaptureTime = 0;
        this.currentFittedHeight = null;
        this.lastFittedHeight = 420;

        // 脏检查签名缓存 (Dirty Checking Caches)
        this.lastRenderedIncoming = null;
        this.lastRenderedEgo = null;
        this.lastRenderedStatus = null;
        this.lastOptionsSignature = null;

        this.initDOMElements();
        this.bindEvents();
        this.fetchContacts();
        this.startPolling();

        // 初始自适应一次高度
        setTimeout(() => this.fitWindowToContent(true), 100);
    }

    initDOMElements() {
        this.capsulePanel = document.getElementById('capsule-panel');
        this.capsuleText = document.getElementById('capsule-text');
        this.btnExpand = document.getElementById('btn-expand');
        this.btnCapsuleQuit = document.getElementById('btn-capsule-quit');

        this.mainContainer = document.getElementById('main-container');
        this.targetSelect = document.getElementById('target-select');
        this.btnToggleView = document.getElementById('btn-toggle-view');
        this.btnFold = document.getElementById('btn-fold');
        this.btnQuit = document.getElementById('btn-quit');

        this.viewMonitor = document.getElementById('view-monitor');
        this.viewIngest = document.getElementById('view-ingest');

        // 看板元素
        this.btnTriggerCapture = document.getElementById('btn-trigger-capture');
        this.targetSenderName = document.getElementById('target-sender-name');
        this.targetMessageTime = document.getElementById('target-message-time');
        this.incomingBox = document.getElementById('incoming-message-box');
        this.egoMessageBox = document.getElementById('ego-message-box');
        this.egoStatusBadge = document.getElementById('ego-status-badge');
        this.dualTrackGrid = document.getElementById('dual-track-grid');

        // 建档视图元素
        this.inputTargetName = document.getElementById('input-target-name');
        this.inputFreeText = document.getElementById('input-free-text');
        this.inputFolderPath = document.getElementById('input-folder-path');
        this.dropZone = document.getElementById('drop-zone');
        this.dropText = document.getElementById('drop-text');
        this.btnResetForm = document.getElementById('btn-reset-form');
        this.btnSubmitOnboard = document.getElementById('btn-submit-onboard');
    }

    bindEvents() {
        // 1. 窗口折叠与展开
        if (this.btnFold) this.btnFold.addEventListener('click', () => this.setCollapsed(true));
        if (this.btnExpand) this.btnExpand.addEventListener('click', () => this.setCollapsed(false));

        // 2. 退出应用
        if (this.btnQuit) this.btnQuit.addEventListener('click', () => this.quitApp());
        if (this.btnCapsuleQuit) this.btnCapsuleQuit.addEventListener('click', () => this.quitApp());

        // 3. 视图切换
        if (this.btnToggleView) {
            this.btnToggleView.addEventListener('click', () => {
                this.switchView(this.currentView === 'monitor' ? 'ingest' : 'monitor');
            });
        }

        // 4. 手动锁定目标联系人
        if (this.targetSelect) {
            this.targetSelect.addEventListener('change', (e) => {
                const target = e.target.value;
                if (!target) return;
                this.activeTarget = target;
                this.updateCapsuleText();
                fetch('/api/target', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ target })
                }).then(() => {
                    this.lastOptionsSignature = null; // 切换联系人时清空缓存触发重新渲染
                    this.fetchPollData();
                }).catch(() => {});
            });
        }

        // 5. 抓取最新 (500ms 快速防重节流)
        if (this.btnTriggerCapture) {
            this.btnTriggerCapture.addEventListener('click', () => this.triggerCapture());
        }

        // 6. 卡片点击即复制 (事件委托)
        if (this.mainContainer) {
            this.mainContainer.addEventListener('click', (e) => {
                const card = e.target.closest('.option-card');
                if (!card) return;
                const replyText = card.getAttribute('data-reply');
                if (replyText) {
                    this.copyToClipboard(replyText, card);
                }
            });
        }

        // 7. 文件夹拖拽处理 (视图 B)
        if (this.dropZone) {
            this.dropZone.addEventListener('dragover', (e) => {
                e.preventDefault();
                this.dropZone.classList.add('dragover');
            });
            this.dropZone.addEventListener('dragleave', () => {
                this.dropZone.classList.remove('dragover');
            });
            this.dropZone.addEventListener('drop', (e) => {
                e.preventDefault();
                this.dropZone.classList.remove('dragover');
                if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    const firstFile = e.dataTransfer.files[0];
                    if (firstFile.path) {
                        this.inputFolderPath.value = firstFile.path;
                        this.dropText.textContent = `已选择: ${firstFile.path}`;
                    }
                }
            });
        }

        // 8. 建档表单操作
        if (this.btnResetForm) {
            this.btnResetForm.addEventListener('click', () => {
                this.inputTargetName.value = '';
                this.inputFreeText.value = '';
                this.inputFolderPath.value = '';
                this.dropText.textContent = '将聊天记录文件夹拖入此处 (或输入绝对路径)';
            });
        }

        if (this.btnSubmitOnboard) {
            this.btnSubmitOnboard.addEventListener('click', () => this.submitOnboard());
        }
    }

    setCollapsed(collapsed) {
        this.isCollapsed = collapsed;
        if (collapsed) {
            this.mainContainer.classList.add('hidden');
            this.capsulePanel.classList.remove('hidden');
            this.updateCapsuleText();
            fetch('/api/window/resize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: 'capsule' })
            }).catch(() => {});
        } else {
            this.capsulePanel.classList.add('hidden');
            this.mainContainer.classList.remove('hidden');
            this.currentFittedHeight = null;
            const targetH = this.lastFittedHeight || 420;
            fetch('/api/window/resize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: 'custom', width: 430, height: targetH })
            }).catch(() => {});
            setTimeout(() => this.fitWindowToContent(true), 80);
        }
    }

    switchView(viewName) {
        this.currentView = viewName;
        if (viewName === 'ingest') {
            this.viewMonitor.classList.add('hidden');
            this.viewIngest.classList.remove('hidden');
            this.btnToggleView.textContent = '返回监控';
        } else {
            this.viewIngest.classList.add('hidden');
            this.viewMonitor.classList.remove('hidden');
            this.btnToggleView.textContent = '导入建档';
        }
        this.currentFittedHeight = null;
        this.fitWindowToContent(true);
    }

    updateCapsuleText() {
        if (this.capsuleText) {
            this.capsuleText.textContent = `侧写 · ${this.activeTarget || '就绪'}`;
        }
    }

    quitApp() {
        fetch('/api/quit', { method: 'POST' }).catch(() => {});
        setTimeout(() => {
            try {
                window.close();
            } catch (_) {}
        }, 120);
    }

    copyToClipboard(text, cardElement) {
        navigator.clipboard.writeText(text).then(() => {
            cardElement.classList.add('copied-glow');
            const badge = cardElement.querySelector('.copy-badge');
            if (badge) {
                const prev = badge.textContent;
                badge.textContent = '已复制';
                setTimeout(() => {
                    cardElement.classList.remove('copied-glow');
                    badge.textContent = prev;
                }, 800);
            }
        }).catch(err => {
            console.error('复制失败', err);
        });
    }

    triggerCapture() {
        const now = Date.now();
        // 500ms 快速冷却防抖
        if (this.isCapturing || (now - this.lastCaptureTime < 500)) {
            return;
        }
        this.isCapturing = true;
        this.lastCaptureTime = now;

        if (this.btnTriggerCapture) {
            this.btnTriggerCapture.textContent = '抓取中...';
            this.btnTriggerCapture.disabled = true;
            this.btnTriggerCapture.style.pointerEvents = 'none';
        }

        const resetBtnState = (delay = 500, text = '抓取最新', color = '') => {
            setTimeout(() => {
                if (this.btnTriggerCapture) {
                    this.btnTriggerCapture.textContent = text;
                    this.btnTriggerCapture.style.color = color;
                    this.btnTriggerCapture.disabled = false;
                    this.btnTriggerCapture.style.pointerEvents = 'auto';
                }
                this.isCapturing = false;
            }, delay);
        };

        fetch('/api/trigger', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target: this.activeTarget })
        })
        .then(res => res.json())
        .then(data => {
            if (this.btnTriggerCapture) {
                if (data.status === 'busy') {
                    this.btnTriggerCapture.textContent = '分析中...';
                    this.btnTriggerCapture.style.color = '#38bdf8';
                    resetBtnState(300);
                    return;
                } else if (data.status === 'mismatch') {
                    const detected = data.detected || '其他窗口';
                    this.btnTriggerCapture.textContent = `目标不符: ${detected.slice(0, 6)}`;
                    this.btnTriggerCapture.style.color = '#f87171';
                    if (this.incomingBox) {
                        const originalIncoming = this.incomingBox.textContent;
                        this.incomingBox.innerHTML = `<span style="color:#f87171;font-weight:600;">【安全阻断】当前微信停留在「${detected}」，非目标「${data.target}」！<br>请在微信中切换至目标聊天窗口后再点击抓取。</span>`;
                        setTimeout(() => {
                            if (this.incomingBox.innerHTML.includes('【安全阻断】')) {
                                this.incomingBox.textContent = originalIncoming;
                            }
                        }, 3000);
                    }
                    resetBtnState(1200);
                    return;
                } else if (data.recorded) {
                    this.btnTriggerCapture.textContent = '已更新并沉淀';
                    this.btnTriggerCapture.style.color = '#34d399';
                    resetBtnState(500);
                } else if (data.case_type === 1) {
                    this.btnTriggerCapture.textContent = '已同步回复';
                    this.btnTriggerCapture.style.color = '#34d399';
                    resetBtnState(500);
                } else {
                    this.btnTriggerCapture.textContent = '已更新建议';
                    this.btnTriggerCapture.style.color = '#38bdf8';
                    resetBtnState(500);
                }
            }
            this.renderPollData(data);
        })
        .catch(err => {
            console.error('抓取失败', err);
            resetBtnState(300);
        });
    }

    fetchContacts() {
        fetch('/api/contacts')
            .then(res => res.json())
            .then(data => {
                if (data.contacts && data.contacts.length > 0) {
                    if (!this.activeTarget || !data.contacts.includes(this.activeTarget)) {
                        this.activeTarget = data.active_target || data.contacts[0];
                    }
                    this.targetSelect.innerHTML = '';
                    data.contacts.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c;
                        opt.textContent = c;
                        if (c === this.activeTarget) opt.selected = true;
                        this.targetSelect.appendChild(opt);
                    });
                    this.targetSelect.value = this.activeTarget;
                    this.updateCapsuleText();
                }
            })
            .catch(() => {});
    }

    submitOnboard() {
        const name = this.inputTargetName.value.trim();
        if (!name) {
            alert('请填写微信备注名');
            return;
        }

        const payload = {
            target_name: name,
            free_text: this.inputFreeText.value.trim(),
            folder_path: this.inputFolderPath.value.trim()
        };

        this.btnSubmitOnboard.textContent = '正在分析建档...';
        this.btnSubmitOnboard.disabled = true;

        fetch('/api/create_contact', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(res => res.json())
        .then(data => {
            this.btnSubmitOnboard.textContent = '智能分析并建档';
            this.btnSubmitOnboard.disabled = false;
            if (data.status === 'success') {
                this.activeTarget = name;
                this.fetchContacts();
                this.switchView('monitor');
            } else {
                alert(`建档失败: ${data.message || '未知错误'}`);
            }
        })
        .catch(() => {
            this.btnSubmitOnboard.textContent = '智能分析并建档';
            this.btnSubmitOnboard.disabled = false;
        });
    }

    startPolling() {
        this.pollTimer = setInterval(() => {
            if (this.currentView === 'monitor' && !this.isCollapsed) {
                this.fetchPollData();
            }
        }, 1500);
    }

    fetchPollData() {
        fetch('/api/poll')
            .then(res => res.json())
            .then(data => this.renderPollData(data))
            .catch(() => {});
    }

    renderPollData(data) {
        if (!data) return;

        // 目标不符安全提示
        if (data.status === 'mismatch') {
            return;
        }

        // 1. 目标联系人名称展示
        if (this.targetSenderName && (data.sender_name || data.target)) {
            const displayName = data.sender_name || data.target;
            if (this.targetSenderName.textContent !== displayName) {
                this.targetSenderName.textContent = displayName;
            }
        }

        // 2. 时间
        if (this.targetMessageTime && data.message_time) {
            if (this.targetMessageTime.textContent !== data.message_time) {
                this.targetMessageTime.textContent = data.message_time;
            }
        }

        // 3. 对方消息看板 (带脏检查)
        if (data.incoming_text && data.incoming_text !== this.lastRenderedIncoming) {
            this.incomingBox.textContent = data.incoming_text;
            this.lastRenderedIncoming = data.incoming_text;
            // 文本变化可能引发高度轻微改变，调度自适应
            this.fitWindowToContent();
        }

        // 4. 我方最新回复看板 (带脏检查)
        const isReplied = data.reply_status === 'replied' || (data.ego_text && data.ego_text !== '暂未回复' && data.ego_text !== '无 (暂未回复)');
        const currentEgoText = isReplied ? (data.ego_text || '已回复') : '无（暂未回复）';
        const currentStatus = isReplied ? 'replied' : 'pending';

        if (currentEgoText !== this.lastRenderedEgo || currentStatus !== this.lastRenderedStatus) {
            this.lastRenderedEgo = currentEgoText;
            this.lastRenderedStatus = currentStatus;

            if (this.egoMessageBox && this.egoStatusBadge) {
                if (isReplied) {
                    this.egoStatusBadge.textContent = '已回复';
                    this.egoStatusBadge.className = 'status-badge badge-replied';
                    this.egoMessageBox.className = 'ego-box';
                    this.egoMessageBox.textContent = currentEgoText;
                } else {
                    this.egoStatusBadge.textContent = '待回复';
                    this.egoStatusBadge.className = 'status-badge badge-pending';
                    this.egoMessageBox.className = 'ego-box pending-state';
                    this.egoMessageBox.textContent = '无（暂未回复）';
                }
            }
            this.fitWindowToContent();
        }

        // 5. 双轨卡片更新 (严格脏检查：仅当 6 选项内容真正变更时重绘 DOM)
        if (data.options && data.options.length === 6) {
            const newSig = data.options.map(o => `${o.slot_id}:${o.reply_text}`).join('|');
            if (newSig !== this.lastOptionsSignature) {
                this.lastOptionsSignature = newSig;
                this.renderCards(data.options);
            }
        }
    }

    renderCards(options) {
        if (!options || options.length !== 6 || !this.dualTrackGrid) return;

        const sorted = [...options].sort((a, b) => a.slot_id - b.slot_id);
        const cardsHtml = `
            <div class="track-header header-native">直觉原句</div>
            <div class="track-header header-evolved">微调提升</div>
            ${sorted.map(o => {
                const isElevated = o.slot_id >= 4;
                return `
                <div class="option-card ${isElevated ? 'card-elevated' : ''}" data-slot="${o.slot_id}" data-reply="${this.escapeHtml(o.reply_text)}">
                    <div class="card-meta">
                        <span class="sub-goal ${isElevated ? 'elevated-tag' : ''}">${this.escapeHtml(o.sub_goal)}</span>
                        <span class="copy-badge">点击复制</span>
                    </div>
                    <div class="card-text">${this.escapeHtml(o.reply_text)}</div>
                </div>
            `;}).join('')}
        `;

        this.dualTrackGrid.innerHTML = cardsHtml;
        this.fitWindowToContent(true);
    }

    fitWindowToContent(force = false) {
        if (this.isCollapsed) return;
        requestAnimationFrame(() => {
            const container = document.getElementById('main-container');
            if (!container || container.classList.contains('hidden')) return;

            // 获取 main-container 的真实高度，收敛在合理界限内 (280px ~ 680px)
            const targetH = Math.min(680, Math.max(280, Math.ceil(container.scrollHeight || container.offsetHeight)));

            // 只有当高度阶跃差距 >= 4px 时才向 Cocoa 宿主调度系统 resize，彻底消除抖动死循环
            if (force || Math.abs(targetH - (this.currentFittedHeight || 0)) >= 4) {
                this.currentFittedHeight = targetH;
                this.lastFittedHeight = targetH;
                fetch('/api/window/resize', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mode: 'custom', width: 430, height: targetH })
                }).catch(() => {});
            }
        });
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;')
                          .replace(/</g, '&lt;')
                          .replace(/>/g, '&gt;')
                          .replace(/"/g, '&quot;')
                          .replace(/'/g, '&#039;');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.echoLens = new EchoLensHUD();
});
