const catalog = document.querySelector("#catalog");
const loadMore = document.querySelector("#load-more");
const status = document.querySelector("#catalog-status");

function card(product) {
  return `
    <article class="product-card" data-product-id="${product.id}">
      <img class="product-image" src="${product.image}" alt="">
      <div>
        <p class="product-category">${product.category}</p>
        <h2 class="product-title">${product.title}</h2>
        <p><span class="product-price">${product.price}</span> <span class="product-currency">${product.currency}</span></p>
        <p class="product-availability">${product.availability}</p>
        <p class="product-rating">${product.rating}</p>
        <a class="product-link" href="${product.detail_url}">View product</a>
      </div>
    </article>`;
}

function insertProducts(items) {
  catalog.insertAdjacentHTML("beforeend", items.map(card).join(""));
}

async function renderScenario() {
  const selectedScenario = new URLSearchParams(window.location.search).get("scenario") || "first";
  const response = await fetch("scenarios.json");
  const scenarios = await response.json();
  const products = scenarios[selectedScenario] || scenarios.first;

  setTimeout(() => {
    insertProducts(products.slice(0, 2));
    status.textContent = `2 products loaded (${selectedScenario} scenario)`;
    loadMore.hidden = false;
  }, 350);

  loadMore.addEventListener("click", () => {
    loadMore.disabled = true;
    loadMore.textContent = "Loading…";
    setTimeout(() => {
      insertProducts(products.slice(2));
      status.textContent = `${products.length} products loaded (${selectedScenario} scenario)`;
      loadMore.remove();
    }, 450);
  });
}

renderScenario().catch(() => {
  status.textContent = "Unable to load local demo scenario.";
});
