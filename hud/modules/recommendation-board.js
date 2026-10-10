/**
 * 侧写 (Cexie) - 双轨建议与僚机洞察模块 (RecommendationBoard)
 * 职责：
 * 1. 独立管理 4 条回复建议卡片（每条标签由模型按当轮对话现起）；
 * 2. 独立管理僚机脚手架（潜台词洞察、避坑预警）；
 * 3. 独立处理单击即复制交互与视觉微动效；
 * 4. 内置数据脏检查与异常隔离。
 */

class RecommendationBoard {
    constructor(windowManager) {
        this.windowManager = windowManager;

        // 缓存 DOM 节点引用
        this.dualTrackGrid = document.getElementById('dual-track-grid');
        this.dualTrackSection = document.querySelector('.dual-track-section');
        this.insightSection = document.getElementById('insight-scaffolding-section');
        this.insightList = document.getElementById('insight-list');
        this.monitorFooter = document.querySelector('.monitor-footer');

        // 脏检查缓存
        this.lastSignature = null;

        // 绑定卡片与词汇胶囊点击复制委托
        this.bindClickEvents();
    }

    bindClickEvents() {
        if (this.dualTrackGrid) {
            this.dualTrackGrid.addEventListener('click', (e) => {
                const card = e.target.closest('.option-card');
                if (card) {
                    const replyText = card.getAttribute('data-reply');
                    if (replyText) {
                        this.copyToClipboard(replyText, card);
                    }
                }
            });
        }
    }

    /**
     * 更新或清除建议卡片
     * @param {Array} options - 回复建议数组 (通常 4 条)
     * @param {Array} insights - 本轮洞察 [{label, text}]
     * @param {string} riskAlert - 避雷提醒 (固定置于洞察末行，防止说错话)
     */
    update(options, insights, riskAlert) {
        if (options && options.length > 0) {
            const sig = options.map(o => `${o.slot_id}:${o.reply_text}`).join('|') +
                '|' + (insights || []).map(it => `${it.label}:${it.text}`).join('|') + `|${riskAlert || ''}`;
            if (sig !== this.lastSignature) {
                this.lastSignature = sig;
                this.renderCards(options, insights, riskAlert);
            }
        } else {
            if (this.lastSignature !== '__CLEARED__') {
                this.lastSignature = '__CLEARED__';
                this.clear();
            }
        }
    }

    renderCards(options, insights, riskAlert) {
        if (!options || options.length === 0 || !this.dualTrackGrid) return;

        // 1. 渲染本轮洞察 (标签与条数均不固定) + 固定的避雷行
        if (this.insightSection) {
            const items = (insights || []).filter(it => it && it.label && it.text);
            if ((items.length > 0 || riskAlert) && this.insightList) {
                const riskHtml = riskAlert ? `
                    <div class="insight-row insight-risk-row">
                        <span class="insight-tag tag-risk">避雷</span>
                        <span class="insight-content">${this.escapeHtml(riskAlert)}</span>
                    </div>
                ` : '';
                this.insightList.innerHTML = items.map(it => `
                    <div class="insight-row">
                        <span class="insight-tag">${this.escapeHtml(it.label)}</span>
                        <span class="insight-content">${this.escapeHtml(it.text)}</span>
                    </div>
                `).join('') + riskHtml;
                this.insightSection.style.display = 'flex';
            } else {
                this.insightSection.style.display = 'none';
            }
        }

        // 2. 展开卡片网格容器与底部提示
        if (this.dualTrackSection) {
            this.dualTrackSection.style.display = '';
        }
        if (this.monitorFooter) {
            this.monitorFooter.style.display = '';
        }

        // 3. 构建 2x2 建议卡片
        const sorted = [...options].sort((a, b) => a.slot_id - b.slot_id);
        const cardsHtml = sorted.map(o => {
            const label = o.sub_goal ? `<span class="sub-goal">${this.escapeHtml(o.sub_goal)}</span>` : '<span></span>';
            const rationaleHtml = o.tactical_rationale ? `<div class="card-rationale">↳ ${this.escapeHtml(o.tactical_rationale)}</div>` : '';
            return `
                <div class="option-card" data-slot="${o.slot_id}" data-reply="${this.escapeHtml(o.reply_text)}">
                    <div class="card-meta">
                        ${label}
                        <span class="copy-badge">点击复制</span>
                    </div>
                    <div class="card-text">${this.escapeHtml(o.reply_text)}</div>
                    ${rationaleHtml}
                </div>
            `;
        }).join('');

        this.dualTrackGrid.innerHTML = cardsHtml;

        if (this.windowManager && typeof this.windowManager.fitWindowToContent === 'function') {
            this.windowManager.fitWindowToContent(true);
        }
    }

    clear() {
        if (this.insightSection) {
            this.insightSection.style.display = 'none';
        }
        if (this.dualTrackSection) {
            this.dualTrackSection.style.display = 'none';
        }
        if (this.dualTrackGrid) {
            this.dualTrackGrid.innerHTML = '';
        }
        if (this.monitorFooter) {
            this.monitorFooter.style.display = 'none';
        }
        if (this.windowManager && typeof this.windowManager.fitWindowToContent === 'function') {
            this.windowManager.fitWindowToContent(true);
        }
    }

    copyToClipboard(text, cardElement) {
        navigator.clipboard.writeText(text).then(() => {
            if (cardElement) {
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
            }
        }).catch(err => {
            console.error('[RecommendationBoard] 复制失败', err);
        });
    }

    escapeHtml(str) {
        return escapeHtml(str);
    }
}

window.RecommendationBoard = RecommendationBoard;
