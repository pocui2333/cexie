/**
 * 侧写 (Cexie) - 双轨建议与破局脚手架模块 (RecommendationBoard)
 * 职责：
 * 1. 独立管理 6 档双轨建议卡片（1-3 原生原话，4-6 微调提升）；
 * 2. 独立管理僚机脚手架（潜台词洞察、避坑预警、破局灵感关键词）；
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
        this.insightSubtextText = document.getElementById('insight-subtext-text');
        this.insightRiskRow = document.getElementById('insight-risk-row');
        this.insightRiskText = document.getElementById('insight-risk-text');
        this.insightChipsContainer = document.getElementById('insight-chips-container');
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

        if (this.insightChipsContainer) {
            this.insightChipsContainer.addEventListener('click', (e) => {
                const chip = e.target.closest('.chip-pill');
                if (chip) {
                    const kw = chip.getAttribute('data-keyword') || chip.textContent;
                    if (kw) {
                        this.copyKeyword(kw, chip);
                    }
                }
            });
        }
    }

    /**
     * 更新或清除建议卡片
     * @param {Array} options - 6 档建议选项数组
     * @param {Object} insight - 僚机脚手架洞察
     */
    update(options, insight) {
        if (options && options.length === 6) {
            const sig = options.map(o => `${o.slot_id}:${o.reply_text}`).join('|') + `|${(insight && insight.subtext) || ''}`;
            if (sig !== this.lastSignature) {
                this.lastSignature = sig;
                this.renderCards(options, insight);
            }
        } else {
            if (this.lastSignature !== '__CLEARED__') {
                this.lastSignature = '__CLEARED__';
                this.clear();
            }
        }
    }

    renderCards(options, insight) {
        if (!options || options.length !== 6 || !this.dualTrackGrid) return;

        // 1. 渲染僚机洞察脚手架
        if (this.insightSection) {
            if (insight && (insight.subtext || (insight.keywords && insight.keywords.length > 0))) {
                this.insightSection.style.display = 'flex';
                if (this.insightSubtextText) {
                    this.insightSubtextText.textContent = insight.subtext || '日常松弛交流 · 享受随性互动';
                }
                if (this.insightRiskRow && this.insightRiskText) {
                    if (insight.risk_alert) {
                        this.insightRiskRow.style.display = 'flex';
                        this.insightRiskText.textContent = insight.risk_alert;
                    } else {
                        this.insightRiskRow.style.display = 'none';
                    }
                }
                if (this.insightChipsContainer) {
                    const kws = (insight.keywords && insight.keywords.length > 0) ? insight.keywords : [];
                    if (kws.length > 0) {
                        this.insightChipsContainer.innerHTML = kws.map(kw => `
                            <span class="chip-pill" data-keyword="${this.escapeHtml(kw)}" title="点击复制词汇">${this.escapeHtml(kw)}</span>
                        `).join('');
                    } else {
                        this.insightChipsContainer.innerHTML = '';
                    }
                }
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

        // 3. 构建 2x3 双轨卡片
        const sorted = [...options].sort((a, b) => a.slot_id - b.slot_id);
        const cardsHtml = `
            <div class="track-header header-native">原生原话</div>
            <div class="track-header header-evolved">微调提升</div>
            ${sorted.map(o => {
                const isElevated = o.slot_id >= 4;
                const rationaleHtml = o.tactical_rationale ? `<div class="card-rationale">↳ ${this.escapeHtml(o.tactical_rationale)}</div>` : '';
                return `
                <div class="option-card ${isElevated ? 'card-elevated' : ''}" data-slot="${o.slot_id}" data-reply="${this.escapeHtml(o.reply_text)}">
                    <div class="card-meta">
                        <span class="sub-goal ${isElevated ? 'elevated-tag' : ''}">${this.escapeHtml(o.sub_goal)}</span>
                        <span class="copy-badge">点击复制</span>
                    </div>
                    <div class="card-text">${this.escapeHtml(o.reply_text)}</div>
                    ${rationaleHtml}
                </div>
            `;}).join('')}
        `;

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

    copyKeyword(kw, chipElement) {
        if (!kw) return;
        navigator.clipboard.writeText(kw).then(() => {
            if (chipElement) {
                const orig = chipElement.textContent;
                chipElement.textContent = '已复制';
                chipElement.classList.add('copied');
                setTimeout(() => {
                    chipElement.textContent = orig;
                    chipElement.classList.remove('copied');
                }, 900);
            }
        }).catch(err => {
            console.error('[RecommendationBoard] 复制词汇失败', err);
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

window.RecommendationBoard = RecommendationBoard;
