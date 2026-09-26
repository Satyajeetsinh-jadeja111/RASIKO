/* Checkout payment page: Razorpay Checkout or Stripe Payment Element, themed with the Vijay palette (no blue). */
(() => {
  "use strict";
  const el = document.getElementById("pay-client");
  if (!el) return;
  const client = JSON.parse(el.textContent);

  if (client.gateway === "razorpay") {
    const form = document.getElementById("rzp-return");
    const open = () => {
      const rzp = new window.Razorpay({
        key: client.key_id,
        order_id: client.order_id,
        amount: client.amount,
        currency: client.currency,
        name: client.name,
        description: client.description,
        prefill: client.prefill,
        theme: { color: "#2FA05A", backdrop_color: "#3E2723" },
        handler: (resp) => {
          form.razorpay_payment_id.value = resp.razorpay_payment_id;
          form.razorpay_order_id.value = resp.razorpay_order_id;
          form.razorpay_signature.value = resp.razorpay_signature;
          form.submit();
        },
      });
      rzp.open();
    };
    document.getElementById("rzp-pay").addEventListener("click", open);
    open();
  }

  if (client.gateway === "stripe") {
    const stripe = window.Stripe(client.publishable_key);
    const elements = stripe.elements({
      clientSecret: client.client_secret,
      appearance: {
        theme: "flat",
        variables: {
          colorPrimary: "#2FA05A",
          colorText: "#3E2723",
          colorTextSecondary: "#6D4C41",
          colorTextPlaceholder: "#8D6E63",
          colorBackground: "#FFF4E0",
          colorDanger: "#B71C2C",
          colorIcon: "#6D4C41",
          fontFamily: "Nunito Sans, system-ui, sans-serif",
          borderRadius: "14px",
          focusBoxShadow: "0 0 0 3px rgba(251,140,0,.35)",
        },
        rules: {
          ".Input": { border: "1.5px solid #F3E3CC" },
          ".Input:focus": { borderColor: "#FB8C00" },
          ".Tab--selected": { borderColor: "#2FA05A", color: "#1B6E42" },
          ".Link": { color: "#1B6E42" },
        },
      },
    });
    elements.create("payment").mount("#stripe-element");
    const form = document.getElementById("stripe-form");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      document.getElementById("stripe-pay").disabled = true;
      const { error } = await stripe.confirmPayment({
        elements,
        confirmParams: { return_url: new URL(form.dataset.return, location.origin).href },
      });
      if (error) {
        const box = document.getElementById("stripe-error");
        box.hidden = false;
        box.textContent = error.message;
        document.getElementById("stripe-pay").disabled = false;
      }
    });
  }
})();
