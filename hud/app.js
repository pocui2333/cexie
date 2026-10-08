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

        // 自动循环抓取状态 (60秒自动轮询)
        this.autoLoopTimer = null;
        this.autoLoopCountdown = 60;
        this.isAutoLooping = false;

        // 统计面板与计时状态
        this.lastReplyTimestamp = null;
        this.statsTimerInterval = null;
        this.lastStatsSignature = null;

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
        this.btnAutoLoop = document.getElementById('btn-auto-loop');
        this.targetSenderName = document.getElementById('target-sender-name');
        this.targetMessageTime = document.getElementById('target-message-time');
        this.incomingBox = document.getElementById('incoming-message-box');
        this.egoMessageBox = document.getElementById('ego-message-box');
        this.egoStatusBadge = document.getElementById('ego-status-badge');
        this.dualTrackGrid = document.getElementById('dual-track-grid');

        // 统计面板元素
        this.statsSection = document.getElementById('stats-section');
        this.statsStatusTag = document.getElementById('stats-status-tag');
        this.statEgoRatio = document.getElementById('stat-ego-ratio');
        this.statTargetRatio = document.getElementById('stat-target-ratio');
        this.statProgressFill = document.getElementById('stat-progress-fill');
        this.statBalanceTip = document.getElementById('stat-balance-tip');
        this.statBalanceDesc = document.getElementById('stat-balance-desc');
        this.statWarmthBadge = document.getElementById('stat-warmth-badge');
        this.statWarmthScore = document.getElementById('stat-warmth-score');
        this.statWarmthWindow = document.getElementById('stat-warmth-window');
        this.statWarmthFill = document.getElementById('stat-warmth-fill');
        this.statWarmthTactic = document.getElementById('stat-warmth-tactic');
        this.statDynamicBadge = document.getElementById('stat-dynamic-badge');
        this.statDynamicTitle = document.getElementById('stat-dynamic-title');
        this.statDynamicDesc = document.getElementById('stat-dynamic-desc');
        this.statTagsContainer = document.getElementById('stat-tags-container');

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

        // 5.1 自动循环抓取 (60秒循环 / 停止)
        if (this.btnAutoLoop) {
            this.btnAutoLoop.addEventListener('click', () => this.toggleAutoLoop());
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
        if (this.isAutoLooping) {
            this.toggleAutoLoop();
        }
        fetch('/api/quit', { method: 'POST' }).catch(() => {});
        setTimeout(() => {
            try {
                window.close();
            } catch (_) {}
        }, 120);
    }

    toggleAutoLoop() {
        const nextState = !this.isAutoLooping;
        fetch('/api/autoloop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: nextState })
        }).then(r => r.json()).then(data => {
            this.isAutoLooping = !!data.auto_loop_enabled;
            this.updateAutoLoopButton(data.auto_loop_countdown);
        }).catch(() => {});
    }

    updateAutoLoopButton(countdown) {
        if (!this.btnAutoLoop) return;
        if (this.isAutoLooping) {
            this.btnAutoLoop.classList.add('active');
            this.btnAutoLoop.textContent = `停止 (${countdown || 60}s)`;
            this.btnAutoLoop.title = '点击停止自动循环抓取';
        } else {
            this.btnAutoLoop.classList.remove('active');
            this.btnAutoLoop.textContent = '自动循环';
            this.btnAutoLoop.title = '开启每60秒自动循环抓取';
        }
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

        // 若处于自动循环中，重置倒计时为 60s，避免刚手动抓完短时间内又重复抓取
        if (this.isAutoLooping) {
            this.autoLoopCountdown = 60;
            if (this.btnAutoLoop) {
                this.btnAutoLoop.textContent = `停止 (${this.autoLoopCountdown}s)`;
            }
        }

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
        let isWindowFocused = true;
        window.addEventListener('focus', () => {
            isWindowFocused = true;
            this.fetchPollData();
        });
        window.addEventListener('blur', () => {
            isWindowFocused = false;
        });

        const scheduleNext = () => {
            // 当窗口失去焦点或处于胶囊折叠态时，拉长轮询间隔至 3500ms，极致省电省资源
            const delay = (this.isCollapsed || !isWindowFocused) ? 3500 : 1500;
            this.pollTimer = setTimeout(() => {
                if (this.currentView === 'monitor') {
                    this.fetchPollData();
                }
                scheduleNext();
            }, delay);
        };
        scheduleNext();
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

        // 后端循环抓取状态同步
        if (data.auto_loop_enabled !== undefined) {
            this.isAutoLooping = !!data.auto_loop_enabled;
            this.updateAutoLoopButton(data.auto_loop_countdown);
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
        const isReplied = data.reply_status === 'replied';
        const currentEgoText = (data.ego_text && data.ego_text !== '暂未回复') ? data.ego_text : (isReplied ? '已回复' : '（暂无上一句发言）');
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
                    this.egoStatusBadge.textContent = '待我回复';
                    this.egoStatusBadge.className = 'status-badge badge-pending';
                    this.egoMessageBox.className = 'ego-box';
                    this.egoMessageBox.textContent = currentEgoText;
                }
            }
            this.fitWindowToContent();
        }

        // 5. 双轨卡片与统计看板切换 (待回复时展开推荐卡片，已回复/无推荐时展示统计看板)
        const isRepliedTurn = data.reply_status === 'replied' || !data.options || data.options.length === 0;
        if (isRepliedTurn) {
            if (this.lastOptionsSignature !== '__CLEARED__') {
                this.lastOptionsSignature = '__CLEARED__';
                this.clearCards();
            }
            this.showStats(data.stats);
        } else if (data.options && data.options.length === 6) {
            this.hideStats();
            const newSig = data.options.map(o => `${o.slot_id}:${o.reply_text}`).join('|');
            if (newSig !== this.lastOptionsSignature) {
                this.lastOptionsSignature = newSig;
                this.renderCards(data.options);
            }
        }
    }

    showStats(stats) {
        if (!this.statsSection) return;
        this.statsSection.style.display = 'flex';

        if (stats) {
            const sig = `${stats.today_ego_count}:${stats.today_target_count}:${stats.warmth_score}:${stats.dynamic_title}:${(stats.today_topics || []).join(',')}`;
            if (sig !== this.lastStatsSignature) {
                this.lastStatsSignature = sig;

                // 1. 今日消息 (相互发送条数与比例)
                const egoCnt = stats.today_ego_count || 0;
                const tgtCnt = stats.today_target_count || 0;
                if (this.statEgoRatio) this.statEgoRatio.textContent = `我 ${egoCnt}条 (${stats.ego_percent || 50}%)`;
                if (this.statTargetRatio) this.statTargetRatio.textContent = `TA ${tgtCnt}条 (${stats.target_percent || 50}%)`;
                if (this.statProgressFill) this.statProgressFill.style.width = `${stats.ego_percent || 50}%`;
                if (this.statBalanceTip) {
                    this.statBalanceTip.textContent = stats.msg_heat_tip || '双向互动';
                }
                if (this.statBalanceDesc) {
                    this.statBalanceDesc.textContent = stats.ratio_desc || '今日互动 · 话轮均衡';
                }

                // 2. 互动热度与兴趣窗口
                const score = (stats.warmth_score !== undefined) ? stats.warmth_score : 80;
                if (this.statWarmthScore) this.statWarmthScore.textContent = score;
                if (this.statWarmthBadge) {
                    this.statWarmthBadge.textContent = stats.warmth_badge || '良好互动';
                    if (score >= 80) {
                        this.statWarmthBadge.className = 'stat-badge badge-amber';
                    } else {
                        this.statWarmthBadge.className = 'stat-badge';
                    }
                }
                if (this.statWarmthWindow) this.statWarmthWindow.textContent = stats.warmth_window || '双向顺畅';
                if (this.statWarmthFill) this.statWarmthFill.style.width = `${Math.min(100, Math.max(0, score))}%`;
                if (this.statWarmthTactic) this.statWarmthTactic.textContent = stats.warmth_tactic || '情绪高位 · 适合顺势拉扯或邀约';

                // 3. 今日动态微观分析
                if (this.statDynamicBadge) {
                    this.statDynamicBadge.textContent = stats.dynamic_title || '日常松弛互动';
                }
                if (this.statDynamicTitle) {
                    this.statDynamicTitle.textContent = stats.dynamic_title || '日常松弛互动';
                }
                if (this.statDynamicDesc) {
                    this.statDynamicDesc.textContent = stats.dynamic_desc || '老友日常碎语交流 · 氛围松弛无压力';
                }

                // 4. 今日话题焦点
                if (this.statTagsContainer) {
                    const tags = (stats.today_topics && stats.today_topics.length > 0) ? stats.today_topics : ['日常', '唠嗑'];
                    this.statTagsContainer.innerHTML = tags.map(t => `<span class="stat-tag">${this.escapeHtml(t)}</span>`).join('');
                }
            }
        }

        this.fitWindowToContent();
    }

    hideStats() {
        if (this.statsSection) {
            this.statsSection.style.display = 'none';
        }
    }

    clearCards() {
        const dualSection = document.querySelector('.dual-track-section');
        if (dualSection) {
            dualSection.style.display = 'none';
        }
        if (this.dualTrackGrid) {
            this.dualTrackGrid.innerHTML = '';
        }
        const footer = document.querySelector('.monitor-footer');
        if (footer) {
            footer.style.display = 'none';
        }
        this.fitWindowToContent(true);
    }

    renderCards(options) {
        if (!options || options.length !== 6 || !this.dualTrackGrid) return;
        this.hideStats();

        const dualSection = document.querySelector('.dual-track-section');
        if (dualSection) {
            dualSection.style.display = '';
        }
        const footer = document.querySelector('.monitor-footer');
        if (footer) {
            footer.style.display = '';
        }

        const sorted = [...options].sort((a, b) => a.slot_id - b.slot_id);
        const cardsHtml = `
            <div class="track-header header-native">原生原话</div>
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

            // 获取 main-container 的真实高度，收敛在合理界限内 (160px ~ 680px)
            const targetH = Math.min(680, Math.max(160, Math.ceil(container.scrollHeight || container.offsetHeight)));

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
