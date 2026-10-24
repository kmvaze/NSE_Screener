export async function onRequestPost({ request, env }) {
  const { razorpay_order_id, razorpay_payment_id, razorpay_signature, user_id } = await request.json();

  // 1. Verify Razorpay Signature securely
  const text = `${razorpay_order_id}|${razorpay_payment_id}`;
  const encoder = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    encoder.encode(env.RAZORPAY_API_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signatureBuffer = await crypto.subtle.sign("HMAC", keyMaterial, encoder.encode(text));
  const signatureHex = Array.from(new Uint8Array(signatureBuffer))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');

  if (signatureHex !== razorpay_signature) {
    return new Response(JSON.stringify({ error: "Invalid payment signature" }), { status: 400 });
  }

  // 2. Advance date by exactly 1 year
  const oneYearFromNow = new Date();
  oneYearFromNow.setFullYear(oneYearFromNow.getFullYear() + 1);

  // 3. Update Supabase bypassing RLS
  const supabaseUrl = `${env.SUPABASE_URL}/rest/v1/profiles?id=eq.${user_id}`;
  const supabaseResponse = await fetch(supabaseUrl, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      "apikey": env.SUPABASE_SERVICE_ROLE_KEY,
      "Authorization": `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`,
      "Prefer": "return=minimal"
    },
    body: JSON.stringify({
      is_pro: true,
      pro_expires_at: oneYearFromNow.toISOString(),
      razorpay_payment_id: razorpay_payment_id
    })
  });

  if (!supabaseResponse.ok) {
    return new Response(JSON.stringify({ error: "Database update failed" }), { status: 500 });
  }

  return new Response(JSON.stringify({ success: true }), { 
    headers: { "Content-Type": "application/json" } 
  });
}