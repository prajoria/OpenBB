using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace OpenBB.ServiceHost.Configuration;

public static class ServiceHostOptionsServiceCollectionExtensions
{
    public static IServiceCollection AddServiceHostOptions(
        this IServiceCollection services,
        IConfigurationSection section)
    {
        ArgumentNullException.ThrowIfNull(services);
        ArgumentNullException.ThrowIfNull(section);

        services.AddOptions<ServiceHostOptions>()
            .ValidateOnStart();
        services.AddSingleton<IConfigureOptions<ServiceHostOptions>>(
            new StrictServiceHostOptionsSetup(section));
        services.AddSingleton<IValidateOptions<ServiceHostOptions>, ServiceHostOptionsValidator>();
        return services;
    }

    private sealed class StrictServiceHostOptionsSetup(IConfigurationSection section)
        : IConfigureOptions<ServiceHostOptions>
    {
        public void Configure(ServiceHostOptions options)
        {
            try
            {
                section.Bind(
                    options,
                    binderOptions => binderOptions.ErrorOnUnknownConfiguration = true);
            }
            catch (InvalidOperationException exception)
            {
                throw new OptionsValidationException(
                    Options.DefaultName,
                    typeof(ServiceHostOptions),
                    [exception.Message]);
            }
        }
    }
}
