/**
 * 侧写 (Cexie) - 数据摄取与建档中心模块 (IngestionHub)
 * 职责：
 * 1. 独立管理摄取中心 3 个子 Tab（联系人建档、追加增量聊天、知识库微策略提炼）；
 * 2. 独立管理文件拖拽上传交互 (Dropzone)；
 * 3. 独立处理与后端摄取接口的异步网络通信与结果回显。
 */

class IngestionHub {
    constructor(options = {}) {
        this.windowManager = options.windowManager;
        this.onContactCreated = options.onContactCreated || (() => {});
        this.getCurrentTarget = options.getCurrentTarget || (() => '');

        // 缓存 DOM 节点引用
        this.ingestTabBtns = document.querySelectorAll('.ingest-tab-btn');
        this.tabPanes = {
            contact: document.getElementById('tab-pane-contact'),
            history: document.getElementById('tab-pane-history'),
            knowledge: document.getElementById('tab-pane-knowledge')
        };

        // Tab 1: 联系人建档
        this.btnFillCurrentTarget = document.getElementById('btn-fill-current-target');
        this.archetypeChips = document.getElementById('archetype-chips');
        this.inputTargetName = document.getElementById('input-target-name');
        this.inputFreeText = document.getElementById('input-free-text');
        this.folderDropzone = document.getElementById('folder-dropzone');
        this.dropzoneText = document.getElementById('dropzone-text');
        this.inputFolderPath = document.getElementById('input-folder-path');
        this.btnResetForm = document.getElementById('btn-reset-form');
        this.btnSubmitOnboard = document.getElementById('btn-submit-onboard');

        // Tab 2: 增量聊天追加分析
        this.selectIncrementalTarget = document.getElementById('select-incremental-target');
        this.historyDropzone = document.getElementById('history-dropzone');
        this.historyDropzoneText = document.getElementById('history-dropzone-text');
        this.inputHistoryPath = document.getElementById('input-history-path');
        this.incrementalFeedback = document.getElementById('incremental-feedback');
        this.btnSubmitIncremental = document.getElementById('btn-submit-incremental');

        // Tab 3: 知识库微策略提炼
        this.inputKbTitle = document.getElementById('input-kb-title');
        this.inputKbText = document.getElementById('input-kb-text');
        this.kbDropzone = document.getElementById('kb-dropzone');
        this.kbDropzoneText = document.getElementById('kb-dropzone-text');
        this.inputKbFilePath = document.getElementById('input-kb-file-path');
        this.kbFeedback = document.getElementById('kb-feedback');
        this.btnSubmitKnowledge = document.getElementById('btn-submit-knowledge');

        this.bindEvents();
    }

    bindEvents() {
        // Tab 切换
        if (this.ingestTabBtns) {
            this.ingestTabBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    const tabKey = btn.getAttribute('data-tab');
                    this.switchTab(tabKey);
                });
            });
        }

        // Tab 1: 建档表单与交互
        if (this.btnFillCurrentTarget) {
            this.btnFillCurrentTarget.addEventListener('click', () => {
                const cur = this.getCurrentTarget();
                if (cur && this.inputTargetName) {
                    this.inputTargetName.value = cur;
                }
            });
        }

        if (this.archetypeChips) {
            this.archetypeChips.addEventListener('click', (e) => {
                const chip = e.target.closest('.arch-chip');
                if (!chip) return;
                const text = chip.getAttribute('data-text');
                if (!text || !this.inputFreeText) return;
                const cur = this.inputFreeText.value.trim();
                if (!cur) {
                    this.inputFreeText.value = text;
                } else if (!cur.includes(text)) {
                    this.inputFreeText.value = `${cur}\n${text}`;
                }
                chip.classList.add('selected');
                setTimeout(() => chip.classList.remove('selected'), 400);
            });
        }

        this.bindDropzone(this.folderDropzone, this.dropzoneText, this.inputFolderPath, '拖入聊天记录目录或单文件 (CSV/JSON/TXT)');

        if (this.btnResetForm) {
            this.btnResetForm.addEventListener('click', () => {
                if (this.inputTargetName) this.inputTargetName.value = '';
                if (this.inputFreeText) this.inputFreeText.value = '';
                if (this.inputFolderPath) this.inputFolderPath.value = '';
                if (this.dropzoneText) this.dropzoneText.textContent = '拖入聊天记录目录或单文件 (CSV/JSON/TXT)';
            });
        }

        if (this.btnSubmitOnboard) {
            this.btnSubmitOnboard.addEventListener('click', () => this.submitOnboard());
        }

        // Tab 2: 增量聊天追加分析
        this.bindDropzone(this.historyDropzone, this.historyDropzoneText, this.inputHistoryPath, '拖入新的聊天记录目录或单文件 (CSV/JSON/TXT)');
        if (this.btnSubmitIncremental) {
            this.btnSubmitIncremental.addEventListener('click', () => this.submitIncrementalHistory());
        }

        // Tab 3: 知识库微策略提炼
        this.bindDropzone(this.kbDropzone, this.kbDropzoneText, this.inputKbFilePath, '或将 md/txt 文件拖入此处');
        if (this.btnSubmitKnowledge) {
            this.btnSubmitKnowledge.addEventListener('click', () => this.submitKnowledge());
        }
    }

    bindDropzone(dropzoneEl, textEl, inputEl, defaultPlaceholder) {
        if (!dropzoneEl || !inputEl) return;
        dropzoneEl.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzoneEl.classList.add('dragover');
        });
        dropzoneEl.addEventListener('dragleave', () => {
            dropzoneEl.classList.remove('dragover');
        });
        dropzoneEl.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzoneEl.classList.remove('dragover');
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                const firstFile = e.dataTransfer.files[0];
                if (firstFile.path) {
                    inputEl.value = firstFile.path;
                    if (textEl) {
                        textEl.textContent = `已选择: ${firstFile.path}`;
                    }
                }
            }
        });
        inputEl.addEventListener('input', () => {
            if (textEl) {
                textEl.textContent = inputEl.value.trim() ? `已指定: ${inputEl.value.trim()}` : defaultPlaceholder;
            }
        });
    }

    switchTab(tabKey) {
        if (this.ingestTabBtns) {
            this.ingestTabBtns.forEach(b => {
                b.classList.toggle('active', b.getAttribute('data-tab') === tabKey);
            });
        }
        if (this.tabPanes) {
            Object.keys(this.tabPanes).forEach(k => {
                const p = this.tabPanes[k];
                if (p) {
                    if (k === tabKey) {
                        p.classList.remove('hidden');
                        p.classList.add('active');
                    } else {
                        p.classList.add('hidden');
                        p.classList.remove('active');
                    }
                }
            });
        }
        if (tabKey === 'history' && this.selectIncrementalTarget) {
            const cur = this.getCurrentTarget();
            if (cur) this.selectIncrementalTarget.value = cur;
        }
        if (this.windowManager && typeof this.windowManager.fitWindowToContent === 'function') {
            this.windowManager.fitWindowToContent(true);
        }
    }

    submitOnboard() {
        const name = this.inputTargetName ? this.inputTargetName.value.trim() : '';
        if (!name) {
            alert('请填写微信备注名');
            return;
        }

        const payload = {
            target_name: name,
            free_text: this.inputFreeText ? this.inputFreeText.value.trim() : '',
            folder_path: this.inputFolderPath ? this.inputFolderPath.value.trim() : ''
        };

        if (this.btnSubmitOnboard) {
            this.btnSubmitOnboard.textContent = '正在分析建档...';
            this.btnSubmitOnboard.disabled = true;
        }

        fetch('/api/create_contact', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(res => res.json())
        .then(data => {
            if (this.btnSubmitOnboard) {
                this.btnSubmitOnboard.textContent = '智能分析并建档';
                this.btnSubmitOnboard.disabled = false;
            }
            if (data.status === 'success') {
                this.onContactCreated(name);
            } else {
                alert(`建档失败: ${data.message || '未知错误'}`);
            }
        })
        .catch(() => {
            if (this.btnSubmitOnboard) {
                this.btnSubmitOnboard.textContent = '智能分析并建档';
                this.btnSubmitOnboard.disabled = false;
            }
        });
    }

    submitIncrementalHistory() {
        const target = this.selectIncrementalTarget ? this.selectIncrementalTarget.value.trim() : '';
        const folderPath = this.inputHistoryPath ? this.inputHistoryPath.value.trim() : '';
        if (!target) {
            alert('请先选择目标联系人');
            return;
        }
        if (!folderPath) {
            alert('请提供聊天记录文件夹或单文件路径 (可直接拖入)');
            return;
        }

        if (this.btnSubmitIncremental) {
            this.btnSubmitIncremental.textContent = 'AI 增量分析中...';
            this.btnSubmitIncremental.disabled = true;
        }
        if (this.incrementalFeedback) {
            this.incrementalFeedback.classList.remove('hidden');
            this.incrementalFeedback.innerHTML = '<div class="feedback-desc">正在脱水并比对消息指纹，提炼事实事件流...</div>';
            if (this.windowManager) this.windowManager.fitWindowToContent(true);
        }

        fetch('/api/ingest_history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target, folder_path: folderPath })
        })
        .then(res => res.json())
        .then(data => {
            if (this.btnSubmitIncremental) {
                this.btnSubmitIncremental.textContent = '追加并增量分析';
                this.btnSubmitIncremental.disabled = false;
            }
            if (this.incrementalFeedback) {
                if (data.status === 'success') {
                    this.incrementalFeedback.innerHTML = `
                        <div class="feedback-title">增量分析完成</div>
                        <div class="feedback-desc">${this.escapeHtml(data.message || '')}</div>
                        <div class="feedback-meta">解析消息: ${data.parsed_messages} 条 · 新增沉淀事件: ${data.episodes_added} 条</div>
                    `;
                    if (this.inputHistoryPath) this.inputHistoryPath.value = '';
                    if (this.historyDropzoneText) this.historyDropzoneText.textContent = '拖入新的聊天记录目录或单文件 (CSV/JSON/TXT)';
                } else {
                    this.incrementalFeedback.innerHTML = `
                        <div class="feedback-title" style="color: #f87171;">分析中断</div>
                        <div class="feedback-desc">${this.escapeHtml(data.message || '未知错误')}</div>
                    `;
                }
                if (this.windowManager) this.windowManager.fitWindowToContent(true);
            }
        })
        .catch(err => {
            if (this.btnSubmitIncremental) {
                this.btnSubmitIncremental.textContent = '追加并增量分析';
                this.btnSubmitIncremental.disabled = false;
            }
            if (this.incrementalFeedback) {
                this.incrementalFeedback.innerHTML = `
                    <div class="feedback-title" style="color: #f87171;">网络或服务异常</div>
                    <div class="feedback-desc">${this.escapeHtml(String(err))}</div>
                `;
                if (this.windowManager) this.windowManager.fitWindowToContent(true);
            }
        });
    }

    submitKnowledge() {
        const title = this.inputKbTitle ? this.inputKbTitle.value.trim() : '';
        const rawText = this.inputKbText ? this.inputKbText.value.trim() : '';
        const filePath = this.inputKbFilePath ? this.inputKbFilePath.value.trim() : '';

        if (!rawText && !filePath) {
            alert('请粘贴攻略长文或拖入 md/txt 文件');
            return;
        }

        if (this.btnSubmitKnowledge) {
            this.btnSubmitKnowledge.textContent = 'AI 深度提炼中...';
            this.btnSubmitKnowledge.disabled = true;
        }
        if (this.kbFeedback) {
            this.kbFeedback.classList.remove('hidden');
            this.kbFeedback.innerHTML = '<div class="feedback-desc">正在运用认知模型提炼情景微策略卡...</div>';
            if (this.windowManager) this.windowManager.fitWindowToContent(true);
        }

        fetch('/api/ingest_knowledge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: rawText, file_path: filePath, source_title: title })
        })
        .then(res => res.json())
        .then(data => {
            if (this.btnSubmitKnowledge) {
                this.btnSubmitKnowledge.textContent = 'AI 提炼为微策略卡';
                this.btnSubmitKnowledge.disabled = false;
            }
            if (this.kbFeedback) {
                if (data.status === 'success') {
                    const card = data.card || data.playbook || {};
                    this.kbFeedback.innerHTML = `
                        <div class="feedback-title">已入库: ${this.escapeHtml(card.title || '微策略卡')}</div>
                        <div class="feedback-desc"><strong>原则:</strong> ${this.escapeHtml(card.principle || '')}<br><strong>雷区:</strong> ${this.escapeHtml(card.taboo || '无')}</div>
                        <div class="feedback-meta">类别: ${this.escapeHtml(card.category || '通用')} · 策略库现存: ${data.total_playbooks} 张卡片 (已即时生效)</div>
                    `;
                    if (this.inputKbTitle) this.inputKbTitle.value = '';
                    if (this.inputKbText) this.inputKbText.value = '';
                    if (this.inputKbFilePath) this.inputKbFilePath.value = '';
                    if (this.kbDropzoneText) this.kbDropzoneText.textContent = '或将 md/txt 文件拖入此处';
                } else {
                    this.kbFeedback.innerHTML = `
                        <div class="feedback-title" style="color: #f87171;">提炼中断</div>
                        <div class="feedback-desc">${this.escapeHtml(data.message || '未知错误')}</div>
                    `;
                }
                if (this.windowManager) this.windowManager.fitWindowToContent(true);
            }
        })
        .catch(err => {
            if (this.btnSubmitKnowledge) {
                this.btnSubmitKnowledge.textContent = 'AI 提炼为微策略卡';
                this.btnSubmitKnowledge.disabled = false;
            }
            if (this.kbFeedback) {
                this.kbFeedback.innerHTML = `
                    <div class="feedback-title" style="color: #f87171;">网络或服务异常</div>
                    <div class="feedback-desc">${this.escapeHtml(String(err))}</div>
                `;
                if (this.windowManager) this.windowManager.fitWindowToContent(true);
            }
        });
    }

    syncContacts(contacts, activeTarget) {
        if (this.selectIncrementalTarget && contacts) {
            this.selectIncrementalTarget.innerHTML = '';
            contacts.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c;
                opt.textContent = c;
                if (c === activeTarget) opt.selected = true;
                this.selectIncrementalTarget.appendChild(opt);
            });
            this.selectIncrementalTarget.value = activeTarget;
        }
    }

    escapeHtml(str) {
        return escapeHtml(str);
    }
}

window.IngestionHub = IngestionHub;
