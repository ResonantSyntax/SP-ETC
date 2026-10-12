/* +6 dB nominal master gain, followed by a gentle summed-output knee.
 * Uses signed 32-bit SG bus frames before final conversion; no sample banks. */
EXPORT u32 kit_master_limited;
static int kit_master_sample(int input){
    float y=(float)input*2,a=kit_absf(y);
    if(a>24576){a=24576+7424*(a-24576)/(7424+a-24576);y=y<0?-a:a;++kit_master_limited;}
    return (int)y;
}
static int kit_mix_baseline[2048];
static int *kit_mix_bus;static int kit_mix_count;
EXPORT void kit_mix_capture(int *bus,int frames,int channels){
    int n=frames*channels;
    kit_mix_count=0;
    if(frames<0||frames>128||channels<1||channels>16||n>2048)return;
    kit_mix_bus=bus;kit_mix_count=n;
    for(int i=0;i<n;++i)kit_mix_baseline[i]=bus[i];
}
EXPORT void kit_mix_finish(int *bus,int frames,int channels){
    if(bus!=kit_mix_bus||frames*channels!=kit_mix_count)return;
    for(int n=0;n<kit_mix_count;++n)bus[n]=kit_mix_baseline[n]+kit_master_sample(bus[n]-kit_mix_baseline[n]);
    kit_mix_count=0;
}
EXPORT int kit_export_mix(int pos,int fp,int limit){
    int y=((int(*)(int,int,int))(KIT_ORIGINAL_EXPORT_MIX|1u))(pos,fp,limit);
    return kit_master_sample(y);
}
__attribute__((naked,used)) EXPORT void kit_mix_gate(void){
    __asm__ volatile("mov r0,r4\nmov r1,r5\nmov r2,r6\nbl kit_mix_finish\npop.w {r4,r5,r6,r7,r8,pc}\n");
}
