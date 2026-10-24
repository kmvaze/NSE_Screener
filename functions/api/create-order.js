export async function onRequestPost() {
  // Hardcode for testing - remove before final production
  const keyId = "rzp_live_Trdtyh6l3mOHtP".trim(); // Paste your actual Key ID here
  const keySecret = "3mLzpP3p0HG3lQN1bdtlstmd".trim(); // Paste your actual Secret here
  
  const auth = btoa(`${keyId}:${keySecret}`);
  
  try {
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
      return new Response(JSON.stringify({ razorpay_rejection: data }), { status: 500 });
    }
    
    return new Response(JSON.stringify(data), { 
      headers: { "Content-Type": "application/json" } 
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), { status: 500 });
  }
}