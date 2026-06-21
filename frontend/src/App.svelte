<script>
  import { onMount, onDestroy } from 'svelte';

  let items = [];
  let newItem = '';
  let userName = '';
  let nameInput = '';
  let showSetup = false;
  let connected = false;
  let eventSource = null;

  onMount(() => {
    const stored = localStorage.getItem('handleliste_name');
    if (stored) {
      userName = stored;
    } else {
      showSetup = true;
    }
    loadItems();
    connectSSE();
  });

  onDestroy(() => {
    eventSource?.close();
  });

  async function loadItems() {
    try {
      const res = await fetch('/api/items');
      items = await res.json();
      connected = true;
    } catch (e) {
      console.error('Klarte ikke å laste varer', e);
    }
  }

  function connectSSE() {
    eventSource = new EventSource('/api/stream');

    eventSource.onopen = () => {
      connected = true;
      // Hent full tilstand på nytt ved hver (gjen)oppkobling, slik at events
      // som ble sendt mens strømmen var nede ikke blir tapt for klienten.
      loadItems();
    };

    eventSource.onmessage = (e) => {
      connected = true;
      const event = JSON.parse(e.data);
      if (event.type === 'add') {
        items = [...items, event.item];
      } else if (event.type === 'update') {
        items = items.map(i => i.id === event.item.id ? event.item : i);
      } else if (event.type === 'delete') {
        items = items.filter(i => i.id !== event.id);
      } else if (event.type === 'delete_checked') {
        items = items.filter(i => !event.ids.includes(i.id));
      }
    };

    eventSource.onerror = () => {
      connected = false;
      eventSource.close();
      setTimeout(connectSSE, 3000);
    };
  }

  async function addItem() {
    const name = newItem.trim();
    if (!name || !userName) return;
    try {
      await fetch('/api/items', {
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
    // Optimistisk oppdatering: flytt varen med en gang slik at UI reagerer
    // umiddelbart, selv om SSE-eventet skulle bli forsinket eller tapt.
    // SSE-eventet setter senere varen til serverens verdi (idempotent).
    items = items.map(i => i.id === id ? { ...i, checked: !i.checked } : i);
    try {
      const res = await fetch(`/api/items/${id}`, { method: 'PATCH' });
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
      items = items.map(i => i.id === id ? { ...i, checked: !i.checked } : i);
      console.error('Klarte ikke å oppdatere vare', e);
    }
  }

  async function deleteItem(id) {
    await fetch(`/api/items/${id}`, { method: 'DELETE' });
  }

  async function clearChecked() {
    await fetch('/api/items', { method: 'DELETE' });
  }

  function saveName() {
    const name = nameInput.trim();
    if (!name) return;
    userName = name;
    localStorage.setItem('handleliste_name', name);
    showSetup = false;
  }

  function handleKeydown(e) {
    if (e.key === 'Enter') addItem();
  }

  function handleNameKeydown(e) {
    if (e.key === 'Enter') saveName();
  }

  $: uncheckedItems = items.filter(i => !i.checked);
  $: checkedItems = items.filter(i => i.checked);
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
{:else}
  <div class="app">
    <header>
      <h1>🛒 Handleliste</h1>
      <div class="header-meta">
        <span class="user-name">{userName}</span>
        <span class="dot">·</span>
        {#if connected}
          <span class="status online">Live</span>
        {:else}
          <span class="status offline">Kobler til...</span>
        {/if}
        <button class="btn-link" on:click={() => { nameInput = userName; showSetup = true; }}>
          Endre
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
</style>
