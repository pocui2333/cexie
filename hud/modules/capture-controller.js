/**
 * 侧写 (Cexie) - 抓取与循环控制模块 (CaptureController)
 * 职责：
 * 1. 独立管理“抓取最新”手动触发流程（500ms 快速防抖、冷却状态、状态回显）；
 * 2. 独立管理“自动循环”后台轮询抓取开关与倒计时显示；
 * 3. 独立处理目标不匹配（安全阻断）与并发防护；
 * 4. 抓取完成后安全回调事件总线分发数据。
 */

class CaptureController {
    constructor(options = {}) {
        this.onCaptureSuccess = options.onCaptureSuccess || (() => {});
        this.onMismatch = options.onMismatch || (() => {});
        this.getTarget = options.getTarget || (() => '');

        // 缓存 DOM 节点引用
        this.btnTriggerCapture = document.getElementById('btn-trigger-capture');
        this.btnAutoLoop = document.getElementById('btn-auto-loop');

        // 内部状态
        this.isCapturing = false;
        this.lastCaptureTime = 0;
        this.isAutoLooping = false;
        this.autoLoopCountdown = 60;

        this.bindEvents();
    }

    bindEvents() {
        if (this.btnTriggerCapture) {
            this.btnTriggerCapture.addEventListener('click', () => this.triggerCapture());
        }

        if (this.btnAutoLoop) {
            this.btnAutoLoop.addEventListener('click', () => this.toggleAutoLoop());
        }
    }

    triggerCapture() {
        const now = Date.now();
        if (this.isCapturing || (now - this.lastCaptureTime < 500)) {
            return;
        }
        this.isCapturing = true;
        this.lastCaptureTime = now;

        // 若处于自动循环中，重置倒计时为 60s
        if (this.isAutoLooping) {
            this.autoLoopCountdown = 60;
            this.updateAutoLoopButton(60);
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

        const target = this.getTarget();

        fetch('/api/trigger', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target })
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
                    this.onMismatch(detected, data.target || target);
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
            this.onCaptureSuccess(data);
        })
        .catch(err => {
            console.error('[CaptureController] 抓取失败', err);
            resetBtnState(300);
        });
    }

    toggleAutoLoop() {
        const nextState = !this.isAutoLooping;
        fetch('/api/autoloop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: nextState })
        })
        .then(r => r.json())
        .then(data => {
            this.isAutoLooping = !!data.auto_loop_enabled;
            this.updateAutoLoopButton(data.auto_loop_countdown);
        })
        .catch(() => {});
    }

    syncState(data) {
        if (!data) return;
        if (data.auto_loop_enabled !== undefined) {
            this.isAutoLooping = !!data.auto_loop_enabled;
            this.updateAutoLoopButton(data.auto_loop_countdown);
        }
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
}

window.CaptureController = CaptureController;
