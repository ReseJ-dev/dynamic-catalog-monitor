const products = [
  {
    id: "product-101",
    title: "Orbit Desk Lamp",
    category: "Lighting",
    price: "$49.99",
    currency: "USD",
    availability: " In Stock ",
    rating: "4.6 out of 5",
    image: "placeholder.svg",
  },
  {
    id: "product-102",
    title: "Harbor Notebook",
    category: "Stationery",
    price: "€ 1.299,99",
    currency: "EUR",
    availability: "OUT OF STOCK",
    rating: "Rated 4.2 / 5",
    image: "placeholder.svg",
  },
  {
    id: "product-103",
    title: "Field Mug",
    category: "Kitchen",
    price: "£18.50",
    currency: "GBP",
    availability: "Limited availability",
    rating: "5",
    image: "placeholder.svg",
  },
  {
    id: "product-invalid",
    title: "Broken Price Example",
    category: "Examples",
    price: "price on request",
    currency: "USD",
    availability: "In Stock",
    rating: "3.8 stars",
    image: "placeholder.svg",
  },
];

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
        <a class="product-link" href="${product.id}.html">View product</a>
      </div>
    </article>`;
}

function insertProducts(items) {
  catalog.insertAdjacentHTML("beforeend", items.map(card).join(""));
}

setTimeout(() => {
  insertProducts(products.slice(0, 2));
  status.textContent = "2 products loaded";
  loadMore.hidden = false;
}, 350);

loadMore.addEventListener("click", () => {
  loadMore.disabled = true;
  loadMore.textContent = "Loading…";
  setTimeout(() => {
    insertProducts(products.slice(2));
    status.textContent = "4 products loaded";
    loadMore.remove();
  }, 450);
});
