document.addEventListener('DOMContentLoaded', () => {
  const status = document.querySelector('#application-status');
  const form = document.querySelector('#application-form');
  const login = document.querySelector('#login-button');
  const userBox = document.querySelector('#application-user');
  const feedback = document.querySelector('#form-feedback');
  let csrf = '';

  const setStatus = (message, error = false) => {
    status.textContent = message;
    status.classList.toggle('notice-error', error);
  };
  const request = async (url, options = {}) => {
    const response = await fetch(url, { credentials: 'same-origin', ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Das hat gerade nicht geklappt. Bitte versuche es erneut.');
    return data;
  };

  async function refreshSession() {
    try {
      const data = await request('/api/me');
      if (!data.authenticated) {
        userBox.classList.add('hide');
        form.classList.add('hide');
        login.classList.remove('hide');
        setStatus(new URLSearchParams(location.search).has('login') ? 'Die Discord-Anmeldung hat nicht geklappt. Bitte starte sie erneut.' : 'Melde dich mit deinem Discord-Account an, um das Formular freizuschalten.');
        return;
      }
      csrf = data.csrf || '';
      login.classList.add('hide');
      userBox.classList.remove('hide');
      document.querySelector('#application-name').textContent = data.user.globalName || data.user.username || 'Discord-Mitglied';
      const avatar = document.querySelector('#application-avatar');
      avatar.src = data.user.avatar
        ? `https://cdn.discordapp.com/avatars/${encodeURIComponent(data.user.id)}/${encodeURIComponent(data.user.avatar)}.png?size=128`
        : `https://cdn.discordapp.com/embed/avatars/${Number(data.user.id) % 6}.png`;
      if (!data.rulesAccepted) {
        form.classList.add('hide');
        setStatus('Fast geschafft! Tritt dem Discord bei, lies die Regeln und akzeptiere sie über den Bot. Lade danach diese Seite neu.');
        return;
      }
      form.classList.remove('hide');
      setStatus('Discord verbunden und Regeln akzeptiert. Du kannst deine Bewerbung jetzt ausfüllen.');
    } catch (error) {
      setStatus(error.message, true);
      login.classList.remove('hide');
    }
  }

  document.querySelector('#logout-button').addEventListener('click', async () => {
    try {
      await request('/api/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrf } });
      location.reload();
    } catch (error) { setStatus(error.message, true); }
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const button = document.querySelector('#submit-application');
    button.disabled = true;
    button.innerHTML = 'Wird sicher gesendet …';
    feedback.textContent = 'Deine Bewerbung wird an das Team übermittelt.';
    feedback.classList.remove('notice-error');
    const data = Object.fromEntries(new FormData(form).entries());
    data.privacy = form.elements.privacy.checked ? 'on' : '';
    try {
      await request('/api/applications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify(data),
      });
      form.reset();
      feedback.textContent = 'Bewerbung ist angekommen! Das CDB-Team meldet sich auf Discord bei dir. 🌱';
      feedback.classList.add('notice-success');
    } catch (error) {
      feedback.textContent = error.message;
      feedback.classList.add('notice-error');
    } finally {
      button.disabled = false;
      button.innerHTML = 'Bewerbung sicher absenden <span>↗</span>';
    }
  });

  refreshSession();
});
