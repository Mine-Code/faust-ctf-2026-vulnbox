window.onload = () => {
    const canvas = document.getElementById('canvas');
    const connectMode = () => document.getElementById('connect-mode').checked;
    let first = null;

    function submitForm(fields) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = '/';
	form.style.display = 'none';
        for (const [name, value] of Object.entries(fields)) {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            input.value = value;
            form.appendChild(input);
        }
        document.body.appendChild(form);
        form.submit();
    }

    canvas.addEventListener('click', function (e) {
        const comp = e.target.closest('[data-id]');

        if (connectMode()) {
            e.preventDefault();
            if (!comp) return;
            if (first === null) {
                first = comp.dataset.id;
                comp.classList.add('selected');
            } else if (comp.dataset.id === first) {
                comp.classList.remove('selected');
                first = null;
            } else {
                submitForm({ action: 'connect', left: first, right: comp.dataset.id });
            }
            return;
        }

        if (comp) return;

        const rect = this.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const typ = document.querySelector('input[name="component"]:checked').value;
        submitForm({ action: 'add', x, y, typ });
    }, true);
};
