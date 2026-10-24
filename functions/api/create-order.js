export async function onRequestPost({ env }) {
  const auth = btoa(`${env.RAZORPAY_KEY_ID}:${env.RAZORPAY_API_SECRET}`);
  
  const response = await fetch("https://api.razorpay.com/v1/orders", {
    method: "POST",
    headers: {
      "Authorization": `Basic ${auth}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      amount: 149900, // ₹1,499.00 in paise
      currency: "INR",
      receipt: `rcpt_${Date.now()}`
    })
  });
  
  const data = await response.json();
  return new Response(JSON.stringify(data), { 
    headers: { "Content-Type": "application/json" } 
  });
}