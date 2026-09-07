(() => {
  // Toda peticion con efectos secundarios (POST/PUT/DELETE) lleva esta cabecera
  // no estandar. Fuerza el preflight CORS, que una pagina de otro origen no
  // puede superar -- mitiga que una pestana externa abierta en el mismo
  // navegador dispare clicks/acciones reales via fetch() a ciegas.
  const HEADER_NAME = 'X-Tibia-Mapper';
  const SIDE_EFFECT_METHODS = new Set(['POST', 'PUT', 'DELETE', 'PATCH']);
  const originalFetch = window.fetch.bind(window);

  window.fetch = (input, init = {}) => {
    const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    if (!SIDE_EFFECT_METHODS.has(method)) {
      return originalFetch(input, init);
    }
    const headers = new Headers(init.headers || (input && input.headers) || {});
    headers.set(HEADER_NAME, '1');
    return originalFetch(input, { ...init, headers });
  };
})();
