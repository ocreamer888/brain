// Types for CSS Modules imported from TypeScript (Vite handles them at build time).
declare module '*.module.css' {
  const classes: Readonly<Record<string, string>>
  export default classes
}
