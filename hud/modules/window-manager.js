/**
 * 侧写 (Cexie) - 窗口与全局状态管理模块 (WindowManager)
 * 职责：
 * 1. 独立管理窗口折叠胶囊态与展开态切换；
 * 2. 独立管理监控视图与数据摄取视图切换；
 * 3. 独立管理多联系人切换与顶栏状态同步；
 * 4. 独立收敛自适应高度计算（严格防抖、>=4px 变化才发起系统级 resize）；
 * 5. 独立管理安全退出应用。
 */

class WindowManager {
    constructor(options = {}) {
        this.onTargetChanged = options.onTargetChanged || (() => {});
        this.onContactsLoaded = options.onContactsLoaded || (() => {});

        // 缓存 DOM 节点引用
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

        // 内部状态
        this.activeTarget = '';
        this.isCollapsed = false;
        this.currentView = 'monitor'; // 'monitor' | 'ingest'
        this.currentFittedHeight = null;
        this.lastFittedHeight = 420;

        this.bindEvents();
    }

    bindEvents() {
        // 1. 折叠与展开
        if (this.btnFold) this.btnFold.addEventListener('click', () => this.setCollapsed(true));
        if (this.btnExpand) this.btnExpand.addEventListener('click', () => this.setCollapsed(false));

        // 2. 退出
        if (this.btnQuit) this.btnQuit.addEventListener('click', () => this.quitApp());
        if (this.btnCapsuleQuit) this.btnCapsuleQuit.addEventListener('click', () => this.quitApp());

        // 3. 视图切换 (监控 <-> 摄取)
        if (this.btnToggleView) {
            this.btnToggleView.addEventListener('click', () => {
                this.switchView(this.currentView === 'monitor' ? 'ingest' : 'monitor');
            });
        }

        // 4. 联系人选择下拉框
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
                    this.onTargetChanged(target);
                }).catch(() => {});
            });
        }
    }

    setCollapsed(collapsed) {
        this.isCollapsed = collapsed;
        if (collapsed) {
            if (this.mainContainer) this.mainContainer.classList.add('hidden');
            if (this.capsulePanel) this.capsulePanel.classList.remove('hidden');
            this.updateCapsuleText();
            fetch('/api/window/resize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: 'capsule' })
            }).catch(() => {});
        } else {
            if (this.capsulePanel) this.capsulePanel.classList.add('hidden');
            if (this.mainContainer) this.mainContainer.classList.remove('hidden');
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
            if (this.viewMonitor) this.viewMonitor.classList.add('hidden');
            if (this.viewIngest) this.viewIngest.classList.remove('hidden');
            if (this.btnToggleView) this.btnToggleView.textContent = '返回监控';
        } else {
            if (this.viewIngest) this.viewIngest.classList.add('hidden');
            if (this.viewMonitor) this.viewMonitor.classList.remove('hidden');
            if (this.btnToggleView) this.btnToggleView.textContent = '导入建档';
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

    fitWindowToContent(force = false) {
        if (this.isCollapsed) return;
        requestAnimationFrame(() => {
            const container = this.mainContainer || document.getElementById('main-container');
            if (!container || container.classList.contains('hidden')) return;

            // 获取真实高度，收敛在 [160, 680] 内
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

    fetchContacts(preferredTarget = '') {
        fetch('/api/contacts')
            .then(res => res.json())
            .then(data => {
                if (data.contacts && data.contacts.length > 0) {
                    if (preferredTarget && data.contacts.includes(preferredTarget)) {
                        this.activeTarget = preferredTarget;
                    } else if (!this.activeTarget || !data.contacts.includes(this.activeTarget)) {
                        this.activeTarget = data.active_target || data.contacts[0];
                    }
                    if (this.targetSelect) {
                        this.targetSelect.innerHTML = '';
                        data.contacts.forEach(c => {
                            const opt = document.createElement('option');
                            opt.value = c;
                            opt.textContent = c;
                            if (c === this.activeTarget) opt.selected = true;
                            this.targetSelect.appendChild(opt);
                        });
                        this.targetSelect.value = this.activeTarget;
                    }
                    this.updateCapsuleText();
                    this.onContactsLoaded(data.contacts, this.activeTarget);
                }
            })
            .catch(() => {});
    }

    syncTarget(target) {
        if (!target) return;
        if (target !== this.activeTarget) {
            this.activeTarget = target;
            if (this.targetSelect) {
                this.targetSelect.value = target;
            }
            this.updateCapsuleText();
        }
    }
}

window.WindowManager = WindowManager;
