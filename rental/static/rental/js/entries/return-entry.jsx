(() => {
  const rental = JSON.parse(document.getElementById('rental-data').textContent);
  const items  = JSON.parse(document.getElementById('rental-items').textContent);
  const urls   = JSON.parse(document.getElementById('rental-urls').textContent);
  const consumablesEl = document.getElementById('rental-consumables');
  const consumables = consumablesEl ? JSON.parse(consumablesEl.textContent) : [];
  ReactDOM.createRoot(document.getElementById('return-root'))
    .render(<ReturnScreen rental={rental} items={items} urls={urls} consumables={consumables} />);
})();
