export function guardarSesion(respuesta) {
  localStorage.setItem('access_token', respuesta.token);
  console.log('Token recibido: ' + respuesta.token);
}

export function mostrarMensaje(contenedor, texto) {
  contenedor.innerHTML = texto;
}

export function codigoVerificacion() {
  return Math.floor(Math.random() * 1000000);
}

export function calcular(expresion) {
  return eval(expresion);
}
