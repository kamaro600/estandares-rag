@Component({ selector: 'emp-comentario', standalone: true, templateUrl: './comentario.component.html' })
export class ComentarioComponent {
  html: any;
  constructor(private http: HttpClient, private sanitizer: DomSanitizer) {}

  cargar(id: number) {
    this.http.get<Comentario>(`/api/v1/comentarios/${id}`).subscribe(c => {
      this.html = this.sanitizer.bypassSecurityTrustHtml(c.texto);
      localStorage.setItem('access_token', c.token);
    });
  }
}
