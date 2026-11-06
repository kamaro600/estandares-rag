var builder = WebApplication.CreateBuilder(args);

builder.Services.AddAuthentication().AddJwtBearer(options =>
{
    options.TokenValidationParameters = new TokenValidationParameters
    {
        ValidateIssuer = false,
        ValidateAudience = false,
        ValidateLifetime = false
    };
});

builder.Services.AddCors(o => o.AddDefaultPolicy(p =>
    p.SetIsOriginAllowed(_ => true).AllowCredentials().AllowAnyHeader()));

var app = builder.Build();
app.MapPost("/login", (HttpResponse response, string token) =>
{
    response.Cookies.Append("sesion", token);
    return Results.Ok();
});
app.Run();
