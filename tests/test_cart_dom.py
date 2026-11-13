"""Cart rows come from localStorage and must not be parsed as HTML."""
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cart_renders_stored_text_without_html():
    script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attrs = {};
    this.className = '';
    this.id = '';
    this.style = {};
    this._text = '';
    this.listeners = {};
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    if (this.children.length) return this.children.map((child) => child.textContent).join('');
    return this._text;
  }
  set innerHTML(_) { throw new Error('innerHTML must not be used'); }
  get innerHTML() { throw new Error('innerHTML must not be used'); }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name === 'id') this.id = String(value);
  }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; }
  append(...nodes) { for (const node of nodes) this.children.push(node); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  closest(selector) { return selector === '.site-cart' ? null : null; }
}

function walk(node, visit) {
  visit(node);
  for (const child of node.children || []) walk(child, visit);
}

const byId = {};
function register(node) {
  if (node.id) byId[node.id] = node;
  return node;
}

const cartItems = new El('div');
cartItems.id = 'cart-items';
register(cartItems);
const cartEmpty = new El('div');
cartEmpty.id = 'cart-empty';
register(cartEmpty);
const cartSummary = new El('div');
cartSummary.id = 'cart-summary';
register(cartSummary);
const subtotal = new El('p');
subtotal.id = 'cart-subtotal';
register(subtotal);
const badge = new El('span');
badge.className = 'cart-count';
const cartLink = new El('a');
cartLink.className = 'site-cart-link';
const roots = [cartItems, cartEmpty, cartSummary, subtotal, badge, cartLink];

const store = new Map();
const document = {
  getElementById(id) { return byId[id] || null; },
  querySelectorAll(selector) {
    const found = [];
    for (const root of roots) {
      walk(root, (node) => {
        if (selector === '.cart-count' && String(node.className).split(/\s+/).includes('cart-count')) found.push(node);
        if (selector === '.site-cart-link' && String(node.className).split(/\s+/).includes('site-cart-link')) found.push(node);
        if (selector === '.product-form') return;
      });
    }
    return found;
  },
  createElement(tag) { return new El(tag); },
};

function render(stored) {
  store.clear();
  if (stored !== undefined) store.set('gang_cart', stored);
  for (const root of roots) root.children = [];
  const context = {
    window: {},
    document,
    localStorage: {
      getItem(key) { return store.has(key) ? store.get(key) : null; },
      setItem(key, value) { store.set(key, String(value)); },
    },
    console,
    URL,
  };
  context.window = context;
  context.window.location = { origin: 'https://gang.tech', href: 'https://gang.tech/cart/' };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
  return { cartItems, cartEmpty, subtotal, badge, cartLink, store };
}

const hostile = JSON.stringify([{
  id: 'v1',
  name: '<img src=x onerror=alert(1)>',
  variant: 'Red "plus"',
  price: '12.5',
  currency: 'USD',
  quantity: '2',
  image: 'javascript:alert(1)',
  sku: '<b>ABC</b>',
}]);
let page = render(hostile);
    assert.strictEqual(page.badge.textContent, '2');
assert.strictEqual(page.cartLink.getAttribute('aria-label'), 'Cart, 2 items');
assert.ok(page.cartItems.textContent.includes('<img src=x onerror=alert(1)>'));
assert.ok(page.cartItems.textContent.includes('SKU: <b>ABC</b>'));
assert.ok(page.cartItems.textContent.includes('USD 12.50'));
assert.ok(page.cartItems.textContent.includes('USD 25.00'));
assert.strictEqual(page.subtotal.textContent, 'USD 25.00');
assert.ok(!page.cartItems.children.some((row) => row.children.some((child) => child.tagName === 'IMG')));

const strings = JSON.stringify([
  { id: 7, quantity: '2', price: 5, currency: 'USD', name: 'One' },
  { id: 8, quantity: '1', price: 4, currency: 'USD', name: 'Two' },
]);
page = render(strings);
assert.strictEqual(page.badge.textContent, '3');
assert.strictEqual(page.subtotal.textContent, 'USD 14.00');

const mixed = JSON.stringify([
  { id: 'a', quantity: 1, price: 10, currency: 'USD', name: 'Dollar' },
  { id: 'b', quantity: 1, price: 9, currency: 'EUR', name: 'Euro' },
]);
page = render(mixed);
assert.strictEqual(page.subtotal.textContent, 'Mixed currencies');

page = render('{"not":"an array"}');
assert.strictEqual(page.cartEmpty.style.display, 'block');
assert.strictEqual(page.cartItems.textContent, '');
assert.strictEqual(page.badge.textContent, '0');

page = render('not json');
assert.strictEqual(page.badge.textContent, '0');
assert.strictEqual(page.cartItems.textContent, '');

console.log('ok');
"""
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "public" / "cart.js")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "innerHTML" not in (ROOT / "public" / "cart.js").read_text()
