# EDGE_FANCONTROL_NATIVE: custom protected PVE node API, not a stock PVE file.
package PVE::API2::EdgeFanControl;

use strict;
use warnings;
use JSON qw(decode_json);
use PVE::JSONSchema qw(get_standard_option);
use PVE::RPCEnvironment;
use PVE::Tools;
use base qw(PVE::RESTHandler);

sub invoke {
    my ($action, $param) = @_;
    my $cmd = ['/usr/bin/python3', '/usr/local/lib/edge-fancontrol/native_api.py', $action];
    if ($action eq 'control') {
        push @$cmd, '--mode', $param->{mode}, '--pwm', "$param->{pwm}",
            '--revision', "$param->{revision}";
    }
    my $output = '';
    PVE::Tools::run_command($cmd, timeout => 10, outfunc => sub {
        $output .= "$_[0]\n";
        die "Fan API response too large\n" if length($output) > 131072;
    });
    my $result = eval { decode_json($output) };
    die "Fan control returned an invalid response\n" if $@ || ref($result) ne 'HASH';
    return $result;
}

__PACKAGE__->register_method({
    name => 'status', path => '', method => 'GET',
    description => 'Read Edge fan controller and hardware status.',
    permissions => { check => ['perm', '/nodes/{node}', ['Sys.Audit']] },
    protected => 1, proxyto => 'node',
    parameters => { additionalProperties => 0,
        properties => { node => get_standard_option('pve-node') } },
    returns => { type => 'object', additionalProperties => 1 },
    code => sub {
        my ($param) = @_;
        my $result = invoke('status', $param);
        my $rpcenv = PVE::RPCEnvironment::get();
        my $allowed = $rpcenv->check($rpcenv->get_user(), "/nodes/$param->{node}", ['Sys.Modify'], 1);
        $result->{native_access} = { can_modify => $allowed ? JSON::true : JSON::false };
        return $result;
    },
});

__PACKAGE__->register_method({
    name => 'control', path => '', method => 'POST',
    description => 'Save and apply Edge fan mode/PWM using the shared controller.',
    permissions => { check => ['perm', '/nodes/{node}', ['Sys.Modify']] },
    protected => 1, proxyto => 'node',
    parameters => { additionalProperties => 0, properties => {
        node => get_standard_option('pve-node'),
        mode => { type => 'string', enum => ['auto', 'manual'], description => 'Saved mode.' },
        pwm => { type => 'integer', minimum => 0, maximum => 255, description => 'Requested PWM.' },
        revision => { type => 'integer', minimum => 0, description => 'Expected saved configuration revision.' },
    } },
    returns => { type => 'object', additionalProperties => 1 },
    code => sub { return invoke('control', $_[0]); },
});

__PACKAGE__->register_method({
    name => 'logs', path => 'logs', method => 'GET',
    description => 'Read the last thirty Edge fan log lines.',
    permissions => { check => ['perm', '/nodes/{node}', ['Sys.Audit']] },
    protected => 1, proxyto => 'node',
    parameters => { additionalProperties => 0,
        properties => { node => get_standard_option('pve-node') } },
    returns => { type => 'object', additionalProperties => 1 },
    code => sub { return invoke('logs', $_[0]); },
});

1;
