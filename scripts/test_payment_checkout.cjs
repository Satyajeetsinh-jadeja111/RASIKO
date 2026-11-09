/* Exercise the real checkout script with simulated browser/provider callbacks. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/pay.js', 'utf8');

function setup({sdk = true, failCreate = false, failVerify = false} = {}) {
  const state = {requests: [], redirect: null};
  const button = {disabled: false, addEventListener: (_name, fn) => {state.click = fn;}};
  const error = {hidden: true, textContent: ''};
  const form = {dataset: {create: '/create/', verify: '/verify/'}, querySelector: () => ({value: 'csrf'})};
  const elements = {'pay-client': {textContent: '{"gateway":"razorpay"}'}, 'rzp-return': form, 'rzp-pay': button, 'rzp-error': error};
  const window = {location: {assign: url => {state.redirect = url;}}};
  if (sdk) window.Razorpay = function(options) {
    state.options = options;
    this.on = (_event, handler) => {state.failed = handler;};
    this.open = () => {state.opened = true;};
  };
  vm.runInNewContext(source, {
    document: {getElementById: id => elements[id]}, window,
    fetch: async (url, options) => {
      state.requests.push({url, options});
      const failed = url === '/create/' ? failCreate : failVerify;
      return {ok: !failed, json: async () => failed ? {error: 'Provider unavailable'} : url === '/create/' ?
        {key_id: 'public', order_id: 'order_1', amount: 100, currency: 'INR'} :
        {success: true, redirect_url: '/success/'}};
    },
  });
  return {...state, state, button, error};
}

(async () => {
  let ui = setup();
  assert.equal(ui.state.requests.length, 0, 'No payment created just by viewing the page');
  await ui.state.click();
  assert.equal(ui.state.opened, true);
  assert.equal(ui.state.requests[0].options.headers['X-CSRFToken'], 'csrf');
  ui.state.options.modal.ondismiss();
  assert.equal(ui.button.disabled, false);
  assert.match(ui.error.textContent, /closed/);
  ui.state.failed({error: {code: 'BAD_REQUEST_ERROR', reason: 'payment_failed', metadata: {payment_id: 'private-id'}}});
  assert.match(ui.error.textContent, /BAD_REQUEST_ERROR: payment_failed/);
  assert.doesNotMatch(ui.error.textContent, /private-id/);
  ui.state.failed({error: {code: '<script>unsafe</script>'}});
  assert.doesNotMatch(ui.error.textContent, /script/);
  await ui.state.options.handler({razorpay_order_id: 'order_1', razorpay_payment_id: 'pay_1', razorpay_signature: 'sig'});
  assert.equal(ui.state.redirect, '/success/');
  assert.equal(JSON.parse(ui.state.requests[1].options.body).razorpay_signature, 'sig');
  ui = setup({sdk: false});
  await ui.state.click();
  assert.match(ui.error.textContent, /could not load/);
  assert.equal(ui.button.disabled, false);
  ui = setup({failCreate: true});
  await ui.state.click();
  assert.equal(ui.state.opened, undefined);
  assert.equal(ui.button.disabled, false);
  ui = setup({failVerify: true});
  await ui.state.click();
  await ui.state.options.handler({razorpay_order_id: 'order_1', razorpay_payment_id: 'pay_1', razorpay_signature: 'sig'});
  assert.equal(ui.state.redirect, null);
  assert.equal(ui.button.disabled, true, 'Uncertain verification must not invite a second payment');
  assert.match(ui.error.textContent, /do not pay again/);
  console.log('Checkout behavior checks passed: success, dismiss, failure, missing SDK, create error, uncertain verification.');
})().catch(error => {console.error(error); process.exitCode = 1;});
