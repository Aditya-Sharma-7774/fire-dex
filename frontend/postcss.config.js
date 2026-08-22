import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// Resolve tailwind.config.js relative to THIS file rather than to the
// current working directory. Without this, starting the dev server from
// anywhere other than `frontend/` makes Tailwind silently fall back to
// defaults -- the custom `coal`/`fire` palette disappears and the build
// fails with "class does not exist".
const here = dirname(fileURLToPath(import.meta.url))

export default {
  plugins: {
    tailwindcss: { config: resolve(here, 'tailwind.config.js') },
    autoprefixer: {},
  },
}
