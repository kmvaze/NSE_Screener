export async function onRequestPost({ env }) {
  // 1. Safety check to ensure Cloudflare is reading your dashboard variables
  if (!env.RAZORPAY_KEY_ID || !env.RAZORPAY_API_SECRET) {
    return new Response(JSON.stringify({ 
      error: "Server configuration error: Missing Razorpay environment variables." 
    }), { 
      status: 500,
      headers: { "Content-Type": "application/json" } 
    });
  }

  // 2. Encode the Basic Auth token
  const auth = btoa(`${env.RAZORPAY_KEY_ID}:${env.RAZORPAY_API_SECRET}`);
  
  try {
    // 3. Request the Order ID from Razorpay
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
    
    // 4. Return the generated order_id to your frontend
    return new Response(JSON.stringify(data), { 
      status: response.status,
      headers: { "Content-Type": "application/json" } 
    });
    
  } catch (error) {
    return new Response(JSON.stringify({ 
      error: "Failed to connect to Razorpay API", 
      details: error.message 
    }), { 
      status: 500,
      headers: { "Content-Type": "application/json" } 
    });
  }
}