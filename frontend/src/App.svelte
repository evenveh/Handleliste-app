<script>
  import { onMount, onDestroy } from 'svelte';

  const NAME_KEY = 'handleliste_name';
  const HOUSEHOLDS_KEY = 'handleliste_households';
  const ACTIVE_KEY = 'handleliste_active';

  let items = [];
  let newItem = '';
  let userName = '';
  let nameInput = '';
  let showSetup = false;
  let connected = false;
  let eventSource = null;
  let reconnectTimer = null;

  // Husstander denne enheten er med i: [{ code, name }]
  let households = [];
  let activeCode = null;
  let showHouseholds = false;

  let joinInput = '';
  let createInput = '';
  let renameInput = '';
  let renaming = false;
  let householdError = '';
  let householdNotice = '';
  let busy = false;
  let shareStatus = '';

  $: activeHousehold = households.find(h => h.code === activeCode) ?? null;
  $: otherHouseholds = households.filter(h => h.code !== activeCode);
  $: uncheckedItems = items.filter(i => !i.checked);
  $: checkedItems = items.filter(i => i.checked);

  onMount(async () => {
    const stored = localStorage.getItem(NAME_KEY);
    if (stored) {
      userName = stored;
    } else {
      showSetup = true;
    }

    try {
      households = JSON.parse(localStorage.getItem(HOUSEHOLDS_KEY) || '[]');
    } catch {
      households = [];
    }
    activeCode = localStorage.getItem(ACTIVE_KEY);
    if (!households.some(h => h.code === activeCode)) {
      activeCode = households[0]?.code ?? null;
    }

    // Invitasjonslenke: /?join=ABCD-EFGH
    const params = new URLSearchParams(location.search);
    const joinCode = params.get('join');
    if (joinCode) {
      history.replaceState(null, '', location.pathname);
      joinInput = joinCode;
      const ok = await joinHousehold();
      if (!ok) showHouseholds = true;
    } else if (activeCode) {
      await refreshActiveHousehold();
    }

    connectSSE();
  });

  onDestroy(() => {
    disconnectSSE();
  });

  // ── Hjelpere ──

  function api(code, path = '') {
    return `/api/households/${encodeURIComponent(code)}${path}`;
  }

  function normalizeCode(code) {
    const clean = code.toUpperCase().replace(/[^A-Z0-9]/g, '');
    return clean.length === 8 ? `${clean.slice(0, 4)}-${clean.slice(4)}` : clean;
  }

  function persistHouseholds() {
    localStorage.setItem(HOUSEHOLDS_KEY, JSON.stringify(households));
    if (activeCode) {
      localStorage.setItem(ACTIVE_KEY, activeCode);
    } else {
      localStorage.removeItem(ACTIVE_KEY);
    }
  }

  function upsertHousehold(household) {
    if (households.some(h => h.code === household.code)) {
      households = households.map(h => h.code === household.code ? household : h);
    } else {
      households = [...households, household];
    }
    persistHouseholds();
  }

  function activate(household) {
    upsertHousehold(household);
    if (activeCode !== household.code) {
      activeCode = household.code;
      items = [];
      persistHouseholds();
      connectSSE();
    }
    showHouseholds = false;
    householdError = '';
    householdNotice = '';
    renaming = false;
  }

  function forgetHousehold(code, notice = '') {
    households = households.filter(h => h.code !== code);
    if (activeCode === code) {
      activeCode = households[0]?.code ?? null;
      items = [];
      connectSSE();
    }
    persistHouseholds();
    householdNotice = notice;
    if (notice) showHouseholds = true;
  }

  // ── Husstander ──

  async function refreshActiveHousehold() {
    const code = activeCode;
    try {
      const res = await fetch(api(code));
      if (code !== activeCode) return;
      if (res.status === 404) {
        forgetHousehold(code, 'Husstanden du var med i finnes ikke lenger.');
      } else if (res.ok) {
        upsertHousehold(await res.json());
      }
    } catch (e) {
      // Offline — behold lagret info og prøv igjen via SSE-gjenoppkobling.
    }
  }

  async function joinHousehold() {
    const code = normalizeCode(joinInput);
    if (!code) return false;
    busy = true;
    householdError = '';
    try {
      const res = await fetch(api(code));
      if (res.status === 404) {
        householdError = 'Fant ingen husstand med den koden.';
        return false;
      }
      if (!res.ok) throw new Error(res.statusText);
      activate(await res.json());
      joinInput = '';
      return true;
    } catch (e) {
      householdError = 'Klarte ikke å koble til. Prøv igjen.';
      return false;
    } finally {
      busy = false;
    }
  }

  async function createHousehold() {
    const name = createInput.trim();
    if (!name) return;
    busy = true;
    householdError = '';
    try {
      const res = await fetch('/api/households', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) throw new Error(res.statusText);
      activate(await res.json());
      createInput = '';
      // Vis koden med en gang, så den kan deles med resten av husstanden.
      showHouseholds = true;
    } catch (e) {
      householdError = 'Klarte ikke å opprette husstanden. Prøv igjen.';
    } finally {
      busy = false;
    }
  }

  async function renameHousehold() {
    const name = renameInput.trim();
    if (!name || !activeHousehold) return;
    const code = activeCode;
    try {
      const res = await fetch(api(code), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) throw new Error(res.statusText);
      upsertHousehold(await res.json());
      renaming = false;
    } catch (e) {
      householdError = 'Klarte ikke å endre navnet.';
    }
  }

  function leaveHousehold() {
    if (!activeHousehold) return;
    const ok = confirm(
      `Forlate «${activeHousehold.name}» på denne enheten?\n\nLista blir ikke slettet, og du kan bli med igjen med koden ${activeHousehold.code}.`
    );
    if (ok) forgetHousehold(activeCode);
  }

  function inviteLink(code) {
    return `${location.origin}/?join=${encodeURIComponent(code)}`;
  }

  async function shareInvite() {
    if (!activeHousehold) return;
    const url = inviteLink(activeHousehold.code);
    const text = `Bli med i handlelista «${activeHousehold.name}». Kode: ${activeHousehold.code}`;
    try {
      if (navigator.share) {
        await navigator.share({ title: 'Handleliste', text, url });
        return;
      }
      await navigator.clipboard.writeText(url);
      shareStatus = 'Lenke kopiert!';
    } catch (e) {
      if (e?.name === 'AbortError') return; // Brukeren avbrøt delingen
      shareStatus = 'Kunne ikke dele — bruk koden over.';
    }
    setTimeout(() => (shareStatus = ''), 2500);
  }

  function openHouseholds() {
    householdError = '';
    householdNotice = '';
    renaming = false;
    showHouseholds = true;
  }

  // ── Varer og sanntid ──

  async function loadItems() {
    const code = activeCode;
    if (!code) return;
    try {
      const res = await fetch(api(code, '/items'));
      if (code !== activeCode) return; // Byttet husstand mens vi ventet
      if (res.status === 404) {
        forgetHousehold(code, 'Husstanden du var med i finnes ikke lenger.');
        return;
      }
      if (!res.ok) return;
      items = await res.json();
    } catch (e) {
      console.error('Klarte ikke å laste varer', e);
    }
  }

  function disconnectSSE() {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
    eventSource?.close();
    eventSource = null;
    connected = false;
  }

  function connectSSE() {
    disconnectSSE();
    const code = activeCode;
    if (!code) return;

    // Vis lista med en gang, uavhengig av når sanntidsstrømmen kommer opp.
    loadItems();

    const es = new EventSource(api(code, '/stream'));
    eventSource = es;

    es.onopen = () => {
      connected = true;
      // Hent full tilstand på nytt ved hver (gjen)oppkobling, slik at events
      // som ble sendt mens strømmen var nede ikke blir tapt for klienten.
      loadItems();
    };

    es.onmessage = (e) => {
      if (eventSource !== es) return;
      connected = true;
      const event = JSON.parse(e.data);
      if (event.type === 'add') {
        if (!items.some(i => i.id === event.item.id)) items = [...items, event.item];
      } else if (event.type === 'update') {
        items = items.map(i => i.id === event.item.id ? event.item : i);
      } else if (event.type === 'delete') {
        items = items.filter(i => i.id !== event.id);
      } else if (event.type === 'delete_checked') {
        items = items.filter(i => !event.ids.includes(i.id));
      } else if (event.type === 'household') {
        upsertHousehold(event.household);
      }
    };

    es.onerror = () => {
      es.close();
      if (eventSource !== es) return;
      eventSource = null;
      connected = false;
      reconnectTimer = setTimeout(async () => {
        reconnectTimer = null;
        if (code !== activeCode) return;
        // Sjekk at husstanden fortsatt finnes før vi prøver igjen.
        await refreshActiveHousehold();
        if (code === activeCode) connectSSE();
      }, 3000);
    };
  }

  async function addItem() {
    const name = newItem.trim();
    if (!name || !userName || !activeCode) return;
    try {
      await fetch(api(activeCode, '/items'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, added_by: userName }),
      });
      newItem = '';
    } catch (e) {
      console.error('Klarte ikke å legge til vare', e);
    }
  }

  async function toggleItem(id) {
    const code = activeCode;
    // Optimistisk oppdatering: flytt varen med en gang slik at UI reagerer
    // umiddelbart, selv om SSE-eventet skulle bli forsinket eller tapt.
    // SSE-eventet setter senere varen til serverens verdi (idempotent).
    items = items.map(i => i.id === id ? { ...i, checked: !i.checked } : i);
    try {
      const res = await fetch(api(code, `/items/${id}`), { method: 'PATCH' });
      if (code !== activeCode) return;
      if (res.status === 404) {
        // Varen ble slettet av noen andre samtidig — fjern spøkelsesvaren lokalt.
        // (fetch kaster ikke på 404, så dette må sjekkes eksplisitt.)
        items = items.filter(i => i.id !== id);
      } else if (!res.ok) {
        // Annen feil — rull tilbake den optimistiske endringen.
        items = items.map(i => i.id === id ? { ...i, checked: !i.checked } : i);
      }
    } catch (e) {
      // Nettverksfeil — rull tilbake.
      if (code === activeCode) {
        items = items.map(i => i.id === id ? { ...i, checked: !i.checked } : i);
      }
      console.error('Klarte ikke å oppdatere vare', e);
    }
  }

  async function deleteItem(id) {
    await fetch(api(activeCode, `/items/${id}`), { method: 'DELETE' });
  }

  async function clearChecked() {
    await fetch(api(activeCode, '/items'), { method: 'DELETE' });
  }

  function saveName() {
    const name = nameInput.trim();
    if (!name) return;
    userName = name;
    localStorage.setItem(NAME_KEY, name);
    showSetup = false;
  }

  function handleKeydown(e) {
    if (e.key === 'Enter') addItem();
  }

  function handleNameKeydown(e) {
    if (e.key === 'Enter') saveName();
  }
</script>

{#if showSetup}
  <div class="setup">
    <div class="setup-card">
      <div class="logo">🛒</div>
      <h1>Handleliste</h1>
      <p>Hva heter du?</p>
      <input
        bind:value={nameInput}
        placeholder="Skriv ditt navn..."
        on:keydown={handleNameKeydown}
        autofocus
        class="name-input"
      />
      <button on:click={saveName} disabled={!nameInput.trim()} class="btn-primary">
        Kom i gang
      </button>
    </div>
  </div>
{:else if !activeHousehold || showHouseholds}
  <div class="setup">
    <div class="setup-card households">
      {#if activeHousehold}
        <button class="btn-close" on:click={() => (showHouseholds = false)} aria-label="Lukk">✕</button>
      {/if}
      <div class="logo">🏠</div>
      <h1>Husstand</h1>

      {#if householdNotice}
        <p class="notice">{householdNotice}</p>
      {/if}

      {#if activeHousehold}
        <section class="current">
          {#if renaming}
            <div class="row">
              <input
                bind:value={renameInput}
                class="name-input"
                maxlength="60"
                on:keydown={(e) => e.key === 'Enter' && renameHousehold()}
                autofocus
              />
              <button class="btn-small" on:click={renameHousehold} disabled={!renameInput.trim()}>Lagre</button>
            </div>
          {:else}
            <div class="current-name">
              <strong>{activeHousehold.name}</strong>
              <button class="btn-link" on:click={() => { renameInput = activeHousehold.name; renaming = true; }}>
                Endre navn
              </button>
            </div>
          {/if}
          <p class="hint">Del koden med de du bor sammen med:</p>
          <div class="code">{activeHousehold.code}</div>
          <button class="btn-primary" on:click={shareInvite}>Del invitasjon</button>
          {#if shareStatus}<p class="hint">{shareStatus}</p>{/if}
          <button class="btn-link danger" on:click={leaveHousehold}>Forlat husstanden</button>
        </section>
      {:else}
        <p>Opprett en ny husstand, eller bli med i en som allerede finnes.</p>
      {/if}

      {#if otherHouseholds.length > 0}
        <section>
          <h2>Bytt husstand</h2>
          <ul class="household-list">
            {#each otherHouseholds as h (h.code)}
              <li>
                <button class="household-btn" on:click={() => activate(h)}>
                  <span>{h.name}</span>
                  <span class="chevron">›</span>
                </button>
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      <section>
        <h2>Bli med med kode</h2>
        <div class="row">
          <input
            bind:value={joinInput}
            placeholder="ABCD-EFGH"
            class="name-input code-input"
            autocapitalize="characters"
            autocomplete="off"
            spellcheck="false"
            on:keydown={(e) => e.key === 'Enter' && joinHousehold()}
          />
          <button class="btn-small" on:click={joinHousehold} disabled={busy || !joinInput.trim()}>Bli med</button>
        </div>
      </section>

      <section>
        <h2>Ny husstand</h2>
        <div class="row">
          <input
            bind:value={createInput}
            placeholder="F.eks. Hjemme"
            class="name-input"
            maxlength="60"
            on:keydown={(e) => e.key === 'Enter' && createHousehold()}
          />
          <button class="btn-small" on:click={createHousehold} disabled={busy || !createInput.trim()}>Opprett</button>
        </div>
      </section>

      {#if householdError}
        <p class="error">{householdError}</p>
      {/if}
    </div>
  </div>
{:else}
  <div class="app">
    <header>
      <button class="household-title" on:click={openHouseholds} aria-label="Bytt eller del husstand">
        <h1>🛒 {activeHousehold.name}</h1>
        <span class="chevron-down">▾</span>
      </button>
      <div class="header-meta">
        <span class="user-name">{userName}</span>
        <span class="dot">·</span>
        {#if connected}
          <span class="status online">Live</span>
        {:else}
          <span class="status offline">Kobler til...</span>
        {/if}
        <button class="btn-link" on:click={() => { nameInput = userName; showSetup = true; }}>
          Endre navn
        </button>
      </div>
    </header>

    <div class="add-bar">
      <input
        bind:value={newItem}
        placeholder="Legg til vare..."
        on:keydown={handleKeydown}
        class="add-input"
      />
      <button on:click={addItem} disabled={!newItem.trim()} class="btn-add" aria-label="Legg til">
        +
      </button>
    </div>

    {#if items.length === 0}
      <div class="empty">
        <p>Handlekurven er tom</p>
        <p class="empty-hint">Legg til det dere trenger!</p>
      </div>
    {:else}
      <ul class="list">
        {#each uncheckedItems as item (item.id)}
          <li class="item">
            <button class="circle-btn" on:click={() => toggleItem(item.id)} aria-label="Kryss av">
              <span class="circle-inner"></span>
            </button>
            <div class="item-text">
              <span class="item-name">{item.name}</span>
              <span class="item-by">{item.added_by}</span>
            </div>
            <button class="remove-btn" on:click={() => deleteItem(item.id)} aria-label="Slett">✕</button>
          </li>
        {/each}

        {#if checkedItems.length > 0}
          <li class="divider">
            <span>Kjøpt ({checkedItems.length})</span>
            <button class="btn-clear" on:click={clearChecked}>Fjern alle</button>
          </li>
          {#each checkedItems as item (item.id)}
            <li class="item is-checked">
              <button class="circle-btn is-checked" on:click={() => toggleItem(item.id)} aria-label="Fjern avkryssing">
                <span class="checkmark">✓</span>
              </button>
              <div class="item-text">
                <span class="item-name">{item.name}</span>
                <span class="item-by">{item.added_by}</span>
              </div>
              <button class="remove-btn" on:click={() => deleteItem(item.id)} aria-label="Slett">✕</button>
            </li>
          {/each}
        {/if}
      </ul>
    {/if}
  </div>
{/if}

<style>
  :global(*, *::before, *::after) {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }

  :global(body) {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f0f2f5;
    color: #1a1a1a;
    -webkit-font-smoothing: antialiased;
  }

  /* ── Setup screen ── */
  .setup {
    min-height: 100svh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }

  .setup-card {
    background: #fff;
    border-radius: 20px;
    padding: 2.5rem 2rem;
    width: 100%;
    max-width: 360px;
    text-align: center;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.10);
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .logo { font-size: 3rem; line-height: 1; }

  .setup-card h1 {
    font-size: 1.75rem;
    font-weight: 700;
  }

  .setup-card p { color: #666; }

  .name-input {
    width: 100%;
    padding: 0.875rem 1rem;
    border: 2px solid #e0e0e0;
    border-radius: 12px;
    font-size: 1rem;
    outline: none;
    transition: border-color 0.15s;
  }

  .name-input:focus { border-color: #4CAF50; }

  /* ── Main app ── */
  .app {
    max-width: 480px;
    margin: 0 auto;
    min-height: 100svh;
  }

  header {
    background: #fff;
    padding: 1rem 1rem 0.75rem;
    border-bottom: 1px solid #e8e8e8;
    position: sticky;
    top: 0;
    z-index: 10;
  }

  header h1 {
    font-size: 1.35rem;
    font-weight: 700;
  }

  .header-meta {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin-top: 0.2rem;
    font-size: 0.82rem;
    color: #888;
  }

  .user-name { font-weight: 600; color: #444; }
  .dot { color: #ccc; }

  .status { font-size: 0.75rem; }
  .online  { color: #4CAF50; }
  .offline { color: #FF9800; }

  .btn-link {
    margin-left: auto;
    background: none;
    border: none;
    color: #aaa;
    font-size: 0.78rem;
    cursor: pointer;
    text-decoration: underline;
    padding: 0;
  }

  /* ── Add bar ── */
  .add-bar {
    display: flex;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    background: #fff;
    border-bottom: 1px solid #e8e8e8;
  }

  .add-input {
    flex: 1;
    padding: 0.75rem 1rem;
    border: 2px solid #e0e0e0;
    border-radius: 12px;
    font-size: 1rem;
    outline: none;
    transition: border-color 0.15s;
  }

  .add-input:focus { border-color: #4CAF50; }

  .btn-add {
    width: 50px;
    height: 50px;
    background: #4CAF50;
    color: #fff;
    border: none;
    border-radius: 12px;
    font-size: 1.6rem;
    line-height: 1;
    cursor: pointer;
    flex-shrink: 0;
    transition: background 0.15s;
  }

  .btn-add:hover:not(:disabled) { background: #43A047; }
  .btn-add:disabled              { background: #ccc; cursor: default; }

  /* ── List ── */
  .list {
    list-style: none;
  }

  .item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.85rem 1rem;
    background: #fff;
    border-bottom: 1px solid #f0f0f0;
  }

  .item.is-checked { opacity: 0.45; }

  .circle-btn {
    width: 38px;
    height: 38px;
    border-radius: 50%;
    border: 2px solid #d0d0d0;
    background: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: border-color 0.15s, background 0.15s;
  }

  .circle-btn:hover { border-color: #4CAF50; }

  .circle-btn.is-checked {
    background: #4CAF50;
    border-color: #4CAF50;
    color: #fff;
  }

  .circle-inner {
    width: 14px;
    height: 14px;
    border-radius: 50%;
  }

  .checkmark { font-size: 1rem; }

  .item-text {
    flex: 1;
    min-width: 0;
  }

  .item-name {
    display: block;
    font-size: 1rem;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .is-checked .item-name { text-decoration: line-through; }

  .item-by {
    display: block;
    font-size: 0.73rem;
    color: #bbb;
    margin-top: 2px;
  }

  .remove-btn {
    background: none;
    border: none;
    color: #d0d0d0;
    font-size: 0.85rem;
    cursor: pointer;
    padding: 0.25rem 0.35rem;
    line-height: 1;
    flex-shrink: 0;
    transition: color 0.15s;
  }

  .remove-btn:hover { color: #f44336; }

  .divider {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.45rem 1rem;
    font-size: 0.78rem;
    color: #bbb;
    background: #f9f9f9;
    border-bottom: 1px solid #f0f0f0;
  }

  .btn-clear {
    background: none;
    border: none;
    color: #f44336;
    font-size: 0.78rem;
    cursor: pointer;
    text-decoration: underline;
    padding: 0;
  }

  /* ── Buttons ── */
  .btn-primary {
    width: 100%;
    padding: 0.875rem;
    background: #4CAF50;
    color: #fff;
    border: none;
    border-radius: 12px;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }

  .btn-primary:hover:not(:disabled) { background: #43A047; }
  .btn-primary:disabled              { background: #ccc; cursor: default; }

  /* ── Empty state ── */
  .empty {
    text-align: center;
    padding: 4rem 1rem;
    color: #bbb;
  }

  .empty-hint {
    margin-top: 0.4rem;
    font-size: 0.85rem;
  }

  /* ── Header: husstandsnavn som knapp ── */
  .household-title {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    max-width: 100%;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    color: inherit;
    text-align: left;
  }

  .household-title h1 {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .chevron-down { color: #aaa; font-size: 0.9rem; }

  /* ── Husstandsskjerm ── */
  .households {
    position: relative;
    text-align: left;
    gap: 1.25rem;
  }

  .households .logo,
  .households h1 { text-align: center; }

  .households section {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .households h2 {
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #999;
  }

  .households .btn-link { margin-left: 0; align-self: center; }

  .btn-close {
    position: absolute;
    top: 1rem;
    right: 1rem;
    background: none;
    border: none;
    color: #aaa;
    font-size: 1.1rem;
    cursor: pointer;
    padding: 0.25rem;
  }

  .current {
    background: #f6f9f6;
    border-radius: 14px;
    padding: 1rem;
    text-align: center;
    align-items: stretch;
  }

  .current-name {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.15rem;
    font-size: 1.1rem;
  }

  .code {
    font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
    font-size: 1.6rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: #2e7d32;
    user-select: all;
  }

  .households .hint { font-size: 0.82rem; color: #888; }

  .row { display: flex; gap: 0.5rem; }
  .row .name-input { flex: 1; min-width: 0; }

  .code-input {
    font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .btn-small {
    padding: 0 1rem;
    background: #4CAF50;
    color: #fff;
    border: none;
    border-radius: 12px;
    font-size: 0.95rem;
    font-weight: 600;
    cursor: pointer;
    flex-shrink: 0;
  }

  .btn-small:hover:not(:disabled) { background: #43A047; }
  .btn-small:disabled              { background: #ccc; cursor: default; }

  .household-list { list-style: none; display: flex; flex-direction: column; gap: 0.4rem; }

  .household-btn {
    width: 100%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.8rem 1rem;
    background: #fff;
    border: 2px solid #e0e0e0;
    border-radius: 12px;
    font-size: 1rem;
    cursor: pointer;
    color: inherit;
    text-align: left;
  }

  .household-btn:hover { border-color: #4CAF50; }
  .chevron { color: #bbb; font-size: 1.3rem; line-height: 1; }

  .danger { color: #e57373; }
  .households .error { color: #f44336; font-size: 0.88rem; text-align: center; }

  .households .notice {
    background: #fff8e1;
    color: #8d6e00;
    border-radius: 10px;
    padding: 0.6rem 0.8rem;
    font-size: 0.88rem;
  }
</style>
