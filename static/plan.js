document.querySelectorAll('[data-expiry]').forEach(node => { node.textContent = new Date(Number(node.dataset.expiry) * 1000).toLocaleString(); });
