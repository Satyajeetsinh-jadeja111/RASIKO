/* Checkout payment page: Razorpay Checkout or Stripe Payment Element, themed with the Vijay palette (no blue). */
(() => {
  "use strict";
  const el = document.getElementById("pay-client");
  if (!el) return;
  const client = JSON.parse(el.textContent);

  if (client.gateway === "razorpay") {
    const form = document.getElementById("rzp-return");
    const button = document.getElementById("rzp-pay");
    const box = document.getElementById("rzp-error");
    const csrf = form.querySelector('[name="csrfmiddlewaretoken"]').value;
    const showError = (message) => {
      box.textContent = message;
      box.hidden = false;
    };
    const post = async (url, data) => {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(data),
      });
      let result;
      try { result = await response.json(); }
      catch { throw new Error("Could not read the payment response. Please sign in again or retry."); }
      if (!response.ok) throw new Error(result.error || "Payment could not be confirmed.");
      return result;
    };
    const open = async () => {
      button.disabled = true;
      box.hidden = true;
      let verifying = false;
      try {
        if (typeof window.Razorpay !== "function") {
          throw new Error("Payment checkout could not load. Check your connection and retry.");
        }
        const checkout = await post(form.dataset.create, {});
        const rzp = new window.Razorpay({
          key: checkout.key_id,
          order_id: checkout.order_id,
          amount: checkout.amount,
          currency: checkout.currency,
          name: checkout.name,
          description: checkout.description,
          prefill: checkout.prefill,
          theme: { color: "#2FA05A", backdrop_color: "#3E2723" },
          modal: {
            ondismiss: () => {
              if (!verifying) {
                button.disabled = false;
                showError("Checkout closed. You can retry while your items are reserved.");
              }
            },
          },
          handler: async (resp) => {
            verifying = true;
            try {
              const result = await post(form.dataset.verify, {
                razorpay_payment_id: resp.razorpay_payment_id,
                razorpay_order_id: resp.razorpay_order_id,
                razorpay_signature: resp.razorpay_signature,
              });
              window.location.assign(result.redirect_url);
            } catch (error) {
              showError(error.message + " If money was deducted, do not pay again; check your order or contact support.");
              // Keep retry disabled after an uncertain verification to avoid a second payment.
            }
          },
        });
        rzp.on("payment.failed", (response) => {
          // Display only diagnostic labels, never provider metadata or payment/account identifiers.
          const labels = [response?.error?.code, response?.error?.reason]
            .filter((value) => typeof value === "string" && /^[a-zA-Z0-9_]{1,80}$/.test(value));
          const detail = labels.length ? " (" + labels.join(": ") + ")" : "";
          showError("Payment failed" + detail + ". You can try another payment method in checkout.");
        });
        rzp.open();
      } catch (error) {
        button.disabled = false;
        showError(error.message || "Could not open payment checkout. Please retry.");
      }
    };
    button.addEventListener("click", open);
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
