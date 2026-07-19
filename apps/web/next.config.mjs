/** @type {import('next').NextConfig} */
const nextConfig = {
    output: 'standalone',
    async headers() {
        // Minimal hardening for a single-user localhost app. CSP intentionally permits
        // Next's inline runtime ('unsafe-inline'/'unsafe-eval'); the high-value wins here
        // are clickjacking + MIME-sniff + framing protection, not a strict script CSP.
        return [{
            source: '/:path*',
            headers: [
                { key: 'X-Frame-Options', value: 'DENY' },
                { key: 'X-Content-Type-Options', value: 'nosniff' },
                { key: 'Referrer-Policy', value: 'same-origin' },
                { key: 'Content-Security-Policy', value:
                    "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; " +
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; " +
                    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'" },
            ],
        }]
    },
};

export default nextConfig;
