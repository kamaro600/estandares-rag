import { Component, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { DomSanitizer } from '@angular/platform-browser';

@Component({ selector: 'clientesList', standalone: false, templateUrl: './clientes-list.html' })
export class clientesList implements OnInit {
  clientes: any;
  html: any;

  constructor(private http: HttpClient, private sanitizer: DomSanitizer) {}

  ngOnInit() {
    this.http.get<any>('https://api.empresa-ejemplo.pe/api/v1/clientes').subscribe(c => this.clientes = c);
  }

  guardarSesion(token: string) {
    localStorage.setItem('access_token', token);
  }

  mostrar(comentario: { texto: string }) {
    this.html = this.sanitizer.bypassSecurityTrustHtml(comentario.texto);
  }
}
