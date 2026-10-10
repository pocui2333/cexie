/**
 * 侧写 (Cexie) - 互动统计与微观分析看板模块 (StatsBoard)
 * 职责：
 * 1. 独立管理今日互动分析看板（今日消息比例、互动热度/兴趣窗口、今日动态、今日话题热词）；
 * 2. 在无建议卡片时展示，作为候场监控面板；
 * 3. 严格数据脏检查与单节点容错。
 */

class StatsBoard {
    constructor(windowManager) {
        this.windowManager = windowManager;

        // 缓存 DOM 节点引用
        this.statsSection = document.getElementById('stats-section');
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

        // 脏检查缓存
        this.lastStatsSignature = null;
    }

    /**
     * 更新统计看板状态
     */
    update(stats, options) {
        if (options && options.length === 6) {
            this.hide();
        } else {
            this.show(stats);
        }
    }

    show(stats) {
        if (!this.statsSection) return;
        this.statsSection.style.display = 'flex';

        if (stats) {
            const sig = `${stats.today_ego_count}:${stats.today_target_count}:${stats.warmth_score}:${stats.dynamic_title}:${(stats.today_topics || []).join(',')}`;
            if (sig !== this.lastStatsSignature) {
                this.lastStatsSignature = sig;

                // 1. 今日消息条数与比例
                const egoCnt = stats.today_ego_count || 0;
                const tgtCnt = stats.today_target_count || 0;
                if (this.statEgoRatio) this.statEgoRatio.textContent = `我 ${egoCnt}条 (${stats.ego_percent || 50}%)`;
                if (this.statTargetRatio) this.statTargetRatio.textContent = `TA ${tgtCnt}条 (${stats.target_percent || 50}%)`;
                if (this.statProgressFill) this.statProgressFill.style.width = `${stats.ego_percent || 50}%`;
                if (this.statBalanceTip) this.statBalanceTip.textContent = stats.msg_heat_tip || '双向互动';
                if (this.statBalanceDesc) this.statBalanceDesc.textContent = stats.ratio_desc || '今日互动 · 话轮均衡';

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
                if (this.statDynamicBadge) this.statDynamicBadge.textContent = stats.dynamic_title || '日常松弛互动';
                if (this.statDynamicTitle) this.statDynamicTitle.textContent = stats.dynamic_title || '日常松弛互动';
                if (this.statDynamicDesc) this.statDynamicDesc.textContent = stats.dynamic_desc || '老友日常碎语交流 · 氛围松弛无压力';

                // 4. 今日话题焦点
                if (this.statTagsContainer) {
                    const tags = (stats.today_topics && stats.today_topics.length > 0) ? stats.today_topics : ['日常', '交流'];
                    this.statTagsContainer.innerHTML = tags.map(t => `<span class="stat-tag">${this.escapeHtml(t)}</span>`).join('');
                }
            }
        }

        if (this.windowManager && typeof this.windowManager.fitWindowToContent === 'function') {
            this.windowManager.fitWindowToContent();
        }
    }

    hide() {
        if (this.statsSection) {
            this.statsSection.style.display = 'none';
        }
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

window.StatsBoard = StatsBoard;
