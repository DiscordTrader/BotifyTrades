/**
 * Diff Viewer — syntax-highlighted unified diff rendering
 * Parses unified diff format and renders with color-coded additions/deletions
 */

const DiffViewer = {
    render(diffText, container) {
        if (!diffText || !container) return;
        container.innerHTML = '';

        const wrapper = document.createElement('div');
        wrapper.className = 'diff-viewer';

        const lines = diffText.split('\n');
        let currentFile = null;
        let fileBlock = null;

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];

            // File header
            if (line.startsWith('--- ') || line.startsWith('+++ ')) {
                if (line.startsWith('+++ ')) {
                    const filename = line.replace('+++ b/', '').replace('+++ ', '');
                    currentFile = filename;
                    fileBlock = document.createElement('div');
                    fileBlock.className = 'diff-file-block';

                    const header = document.createElement('div');
                    header.className = 'diff-file-header';
                    header.innerHTML = `<span class="diff-file-icon">&#128196;</span><span class="diff-file-name">${this.escape(filename)}</span>`;
                    fileBlock.appendChild(header);

                    const codeBlock = document.createElement('div');
                    codeBlock.className = 'diff-code-block';
                    fileBlock.codeBlock = codeBlock;
                    fileBlock.appendChild(codeBlock);
                    wrapper.appendChild(fileBlock);
                }
                continue;
            }

            // Hunk header
            if (line.startsWith('@@')) {
                if (!fileBlock) {
                    fileBlock = document.createElement('div');
                    fileBlock.className = 'diff-file-block';
                    const codeBlock = document.createElement('div');
                    codeBlock.className = 'diff-code-block';
                    fileBlock.codeBlock = codeBlock;
                    fileBlock.appendChild(codeBlock);
                    wrapper.appendChild(fileBlock);
                }
                const hunkLine = document.createElement('div');
                hunkLine.className = 'diff-line diff-hunk';
                hunkLine.textContent = line;
                fileBlock.codeBlock.appendChild(hunkLine);
                continue;
            }

            if (!fileBlock || !fileBlock.codeBlock) continue;

            const diffLine = document.createElement('div');

            if (line.startsWith('+')) {
                diffLine.className = 'diff-line diff-add';
                diffLine.innerHTML = `<span class="diff-marker">+</span><span class="diff-text">${this.escape(line.substring(1))}</span>`;
            } else if (line.startsWith('-')) {
                diffLine.className = 'diff-line diff-del';
                diffLine.innerHTML = `<span class="diff-marker">-</span><span class="diff-text">${this.escape(line.substring(1))}</span>`;
            } else if (line.startsWith(' ')) {
                diffLine.className = 'diff-line diff-ctx';
                diffLine.innerHTML = `<span class="diff-marker"> </span><span class="diff-text">${this.escape(line.substring(1))}</span>`;
            } else if (line.trim() === '') {
                diffLine.className = 'diff-line diff-ctx';
                diffLine.innerHTML = '<span class="diff-marker"> </span><span class="diff-text"></span>';
            } else {
                continue;
            }

            fileBlock.codeBlock.appendChild(diffLine);
        }

        container.appendChild(wrapper);
    },

    renderFromMetadata(metadata, container) {
        if (!container) return;
        container.innerHTML = '';

        if (metadata.diff) {
            this.render(metadata.diff, container);
            return;
        }

        if (metadata.files && Array.isArray(metadata.files)) {
            const wrapper = document.createElement('div');
            wrapper.className = 'diff-viewer';

            metadata.files.forEach(f => {
                const fileInfo = document.createElement('div');
                fileInfo.className = 'diff-file-block';

                const header = document.createElement('div');
                header.className = 'diff-file-header';
                const action = f.action || 'modified';
                const actionClass = action === 'create' ? 'diff-action-add' : action === 'delete' ? 'diff-action-del' : '';
                header.innerHTML = `<span class="diff-file-icon">&#128196;</span><span class="diff-file-name">${this.escape(f.path || f)}</span><span class="diff-action ${actionClass}">${this.escape(action)}</span>`;
                fileInfo.appendChild(header);

                if (f.diff) {
                    const codeBlock = document.createElement('div');
                    codeBlock.className = 'diff-code-block';
                    fileInfo.appendChild(codeBlock);
                    fileInfo.codeBlock = codeBlock;
                    // Mini render
                    f.diff.split('\n').forEach(line => {
                        const dl = document.createElement('div');
                        if (line.startsWith('+')) { dl.className = 'diff-line diff-add'; }
                        else if (line.startsWith('-')) { dl.className = 'diff-line diff-del'; }
                        else if (line.startsWith('@@')) { dl.className = 'diff-line diff-hunk'; }
                        else { dl.className = 'diff-line diff-ctx'; }
                        dl.textContent = line;
                        codeBlock.appendChild(dl);
                    });
                }

                wrapper.appendChild(fileInfo);
            });

            container.appendChild(wrapper);
            return;
        }

        container.innerHTML = '<div class="empty-state">No diff data available</div>';
    },

    escape(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};
