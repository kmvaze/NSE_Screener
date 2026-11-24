export async function onRequestPost({ env }) {
  // 1. Strict validation of environment variables
  if (!env.RAZORPAY_KEY_ID || !env.RAZORPAY_API_SECRET) {
    return new Response(JSON.stringify({ 
      error: "Server configuration error: Missing Razorpay credentials." 
    }), { 
      status: 500,
      headers: { "Content-Type": "application/json" } 
    });
  }

  // 2. Forcefully remove any hidden spaces
  const keyId = env.RAZORPAY_KEY_ID.trim();
  const keySecret = env.RAZORPAY_API_SECRET.trim();
  
  // 3. Cryptographic encoding for Basic Auth
  const auth = btoa(`${keyId}:${keySecret}`);
  
  try {
    // 4. Mint the Order ID on Razorpay's servers
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
    
    // Explicitly catch and return Razorpay rejections
    if (!response.ok) {
      return new Response(JSON.stringify({ razorpay_rejection: data }), { 
        status: 500,
        headers: { "Content-Type": "application/json" } 
      });
    }
    
    // Return the clean order payload to the frontend
    return new Response(JSON.stringify(data), { 
      status: 200,
      headers: { "Content-Type": "application/json" } 
    });
    
  } catch (error) {
    return new Response(JSON.stringify({ 
      error: "Network failure while reaching Razorpay API", 
      details: error.message 
    }), { 
      status: 500,
      headers: { "Content-Type": "application/json" } 
    });
  }
}