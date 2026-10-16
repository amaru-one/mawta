// Command chatkey generates a signing key pair for the director's chat token
// (GET /auth/chat-token): the seed goes to mawta-server, the public key to
// the chat service. It prints a secret, so run it locally and copy the values
// into /srv/mawta/.env by hand.
//
// Rotation: generate a pair with a new -kid, add its public key to the chat
// service next to the old one, switch mawta-server to the new seed and key
// id, and remove the old public key once the old tokens have expired
// (CHAT_TOKEN_TTL, 1h by default).
package main

import (
	"flag"
	"fmt"
	"os"

	"mawta-server/internal/chattoken"
)

func main() {
	kid := flag.String("kid", "", "key id written in the token header, e.g. k1; required")
	flag.Parse()
	if *kid == "" {
		fmt.Fprintln(os.Stderr, "chatkey: -kid is required")
		os.Exit(2)
	}

	seed, public, err := chattoken.GenerateKey()
	if err != nil {
		fmt.Fprintln(os.Stderr, "chatkey:", err)
		os.Exit(1)
	}

	fmt.Println("# mawta-server (/srv/mawta/.env) — secret, never share or commit")
	fmt.Printf("CHAT_TOKEN_KEY_ID=%s\n", *kid)
	fmt.Printf("CHAT_TOKEN_SIGNING_KEY=%s\n", seed)
	fmt.Println()
	fmt.Println("# chat service — public key, safe to share")
	fmt.Printf("CHAT_TOKEN_PUBLIC_KEYS={\"%s\":\"%s\"}\n", *kid, public)
}
