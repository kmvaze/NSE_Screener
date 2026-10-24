export async function onRequestPost({ env }) {
  // Use the env variables if you updated them, or hardcode them to test
  const auth = btoa(`${env.RAZORPAY_KEY_ID}:${env.RAZORPAY_API_SECRET}`);
  
  const response = await fetch("https://api.razorpay.com/v1/orders", {
    method: "POST",
    headers: {
      "Authorization": `Basic ${auth}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ amount: 149900, currency: "INR", receipt: `rcpt_${Date.now()}` })
  });
  
  const data = await response.json();
  
  // If Razorpay rejects it, return the exact error message with a 500 status
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