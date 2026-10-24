export async function onRequestPost() {
  // Hardcode for testing - remove before final production
  const keyId = "rzp_test_TrPlayU2sCwVm1".trim(); // Paste your actual Key ID here
  const keySecret = "VcyyUj0X1s9hCGyvTzrk6lpv".trim(); // Paste your actual Secret here
  
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