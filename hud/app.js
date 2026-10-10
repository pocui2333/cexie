/**
 * 侧写 (Cexie) - HUD 交互总线与协同中枢 (App Orchestrator)
 * 
 * 核心架构准则：
 * 1. 严格模块化解耦：上下文展示、建议卡片、抓取控制、数据摄取与窗口管理均独立为单一职责模块；
 * 2. 故障完全隔离：各模块在总线分发中通过 try-catch 严格沙箱隔离，任何单一模块的异常绝不波及其他模块；
 * 3. 响应式单向数据流：通过定时轮询及抓取回调获取单源数据，切片分发至各模块；
 * 4. 极致平滑：支持按窗口焦点自适应调节轮询频率，结合各模块自身的脏检查机制杜绝 UI 闪烁。
 */

class EchoLensApp {
    constructor() {
        this.pollTimer = null;
        this.isWindowFocused = true;

        this.initModules();
        this.initPolling();

        // 初始自适应一次高度
        setTimeout(() => {
            if (this.windowManager) {
                this.windowManager.fitWindowToContent(true);
            }
        }, 120);
    }

    initModules() {
        // 1. 窗口与全局状态管理模块
        this.windowManager = new WindowManager({
            onTargetChanged: (target) => {
                if (this.recommendationBoard) {
                    this.recommendationBoard.lastSignature = null;
                }
                this.fetchPollData();
            },
            onContactsLoaded: (contacts, activeTarget) => {
                if (this.ingestionHub) {
                    this.ingestionHub.syncContacts(contacts, activeTarget);
                }
            }
        });

        // 2. 对话上下文展示模块 (对方消息、我方最新回复、状态指示)
        this.contextViewer = new ContextViewer(this.windowManager);

        // 3. 双轨建议卡片与僚机洞察模块
        this.recommendationBoard = new RecommendationBoard(this.windowManager);

        // 4. 抓取与循环控制模块
        this.captureController = new CaptureController({
            getTarget: () => this.windowManager ? this.windowManager.activeTarget : '',
            onCaptureSuccess: (data) => this.dispatchData(data),
            onMismatch: (detected, target) => {
                if (this.contextViewer) {
                    this.contextViewer.showMismatchAlert(detected, target);
                }
            }
        });

        // 5. 数据摄取与建档中心模块
        this.ingestionHub = new IngestionHub({
            windowManager: this.windowManager,
            getCurrentTarget: () => this.windowManager ? this.windowManager.activeTarget : '',
            onContactCreated: (name) => {
                if (this.windowManager) {
                    this.windowManager.fetchContacts(name);
                    this.windowManager.switchView('monitor');
                }
            }
        });

        // 初始化联系人列表
        this.windowManager.fetchContacts();
    }

    initPolling() {
        window.addEventListener('focus', () => {
            this.isWindowFocused = true;
            this.fetchPollData();
        });

        window.addEventListener('blur', () => {
            this.isWindowFocused = false;
        });

        const scheduleNext = () => {
            const isCollapsed = this.windowManager ? this.windowManager.isCollapsed : false;
            // 当窗口失去焦点或处于胶囊折叠态时，拉长轮询间隔至 3500ms 节省资源
            const delay = (isCollapsed || !this.isWindowFocused) ? 3500 : 1500;
            this.pollTimer = setTimeout(() => {
                const currentView = this.windowManager ? this.windowManager.currentView : 'monitor';
                if (currentView === 'monitor') {
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
            .then(data => this.dispatchData(data))
            .catch(() => {});
    }

    /**
     * 核心数据总线分发 (各模块沙箱隔离)
     * @param {Object} data - 后端全量数据切片
     */
    dispatchData(data) {
        if (!data) return;

        // 目标不符安全阻断
        if (data.status === 'mismatch') {
            return;
        }

        // 1. 同步目标联系人与顶栏信息
        try {
            if (this.windowManager) {
                this.windowManager.syncTarget(data.target || data.sender_name);
            }
        } catch (e) {
            console.error('[App] WindowManager syncTarget failed:', e);
        }

        // 2. 同步后台自动循环与倒计时状态
        try {
            if (this.captureController) {
                this.captureController.syncState(data);
            }
        } catch (e) {
            console.error('[App] CaptureController syncState failed:', e);
        }

        // 3. 更新对话上下文看板 (对方消息 + 我方最新回复)
        try {
            if (this.contextViewer) {
                this.contextViewer.update(data);
            }
        } catch (e) {
            console.error('[App] ContextViewer update failed:', e);
        }

        // 4. 更新双轨建议卡片与僚机洞察
        try {
            if (this.recommendationBoard) {
                this.recommendationBoard.update(data.options, data.insights, data.risk_alert);
            }
        } catch (e) {
            console.error('[App] RecommendationBoard update failed:', e);
        }
    }
}

// 页面加载完成后启动总线
document.addEventListener('DOMContentLoaded', () => {
    window.echoLensApp = new EchoLensApp();
});
