export async function onRequestPost({ env }) {
  // Forcefully remove invisible spaces and newlines from the dashboard variables
  const keyId = env.RAZORPAY_KEY_ID.trim();
  const keySecret = env.RAZORPAY_API_SECRET.trim();
  
  const auth = btoa(`${keyId}:${keySecret}`);
  
  const response = await fetch("https://api.razorpay.com/v1/orders", {
    method: "POST",
    headers: {
      "Authorization": `Basic ${auth}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ amount: 149900, currency: "INR", receipt: `rcpt_${Date.now()}` })
  });
  
  const data = await response.json();
  
  if (!response.ok) {
    return new Response(JSON.stringify({ razorpay_rejection: data }), { 
      status: 500,
      headers: { "Content-Type": "application/json" } 
    });
  }
  
  return new Response(JSON.stringify(data), { 
    headers: { "Content-Type": "application/json" } 
  });
}