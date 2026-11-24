// Derived from Rapfi InternalConfig at 1387d11312190ec66665d361ff07a7c70221b78a.
// Copyright (C) 2022 Rapfi developers. GPL-3.0-or-later.
// Direct initialization equivalent to the official built-in TOML classic model.
// Must run after PatternConfig::PCODE initialization, before Board construction.
inline void initializeEmbeddedClassicalModel() {
    static const int normal[136] = {0,0,0,0,0,0,0,0,0,0,0,0,0,0,36,41,0,0,0,0,0,0,0,0,0,0,0,0,0,36,41,0,0,0,1,1,1,2,2,9,9,16,16,36,41,0,0,1,1,1,2,2,10,10,17,17,38,43,1,2,2,2,3,3,11,11,19,19,39,44,3,3,3,4,4,13,13,20,20,42,47,3,3,4,4,13,13,20,20,42,47,3,4,4,13,13,20,20,42,47,5,5,14,14,22,22,43,49,5,14,14,22,22,43,49,25,25,34,34,57,62,25,34,34,57,62,43,43,67,72,43,67,72,93,99,105};
    static const int renju[136] = {0,0,0,0,0,1,1,1,2,2,9,9,15,15,36,40,0,0,0,0,1,1,1,2,2,9,9,15,15,36,40,0,0,0,1,1,1,2,2,9,9,15,15,36,40,0,0,1,1,1,2,2,9,9,15,15,37,40,1,2,2,2,3,3,10,10,17,17,38,42,3,3,3,4,4,12,12,18,18,40,44,3,3,4,4,12,12,18,18,40,44,3,4,4,12,12,18,18,40,44,5,5,13,13,20,20,42,46,5,13,13,20,20,42,46,23,23,30,30,54,58,23,30,30,54,58,38,38,63,67,38,63,67,90,94,99};
    static const int moveScore[16] = {-1,0,0,1,2,6,6,6,9,9,16,20,30,30,100,500};
    auto pairIndex = [](int a,int b) { return a*16+b-a*(a+1)/2; };
    std::memset(Evaluation::EVALS,0,sizeof(Evaluation::EVALS));
    std::memset(Evaluation::EVALS_THREAT,0,sizeof(Evaluation::EVALS_THREAT));
    std::memset(Evaluation::P4SCORES,0,sizeof(Evaluation::P4SCORES));
    for(int a=0;a<16;++a) for(int b=a;b<16;++b)
    for(int c=b;c<16;++c) for(int d=c;d<16;++d) {
        const auto code=PatternConfig::PCODE[a][b][c][d].pcode();
        const int ordering=moveScore[a]+moveScore[b]+moveScore[c]+moveScore[d];
        for(int table=0;table<RULE_NB+1;++table) {
            const int* weights=table>=int(RENJU)?renju:normal;
            int value=weights[pairIndex(a,b)]+weights[pairIndex(a,c)]+weights[pairIndex(a,d)]
                     +weights[pairIndex(b,c)]+weights[pairIndex(b,d)]+weights[pairIndex(c,d)];
            Evaluation::EVALS[table][code]=static_cast<Eval>(value);
            Evaluation::P4SCORES[table][code][0]=static_cast<Score>(ordering*2);
            Evaluation::P4SCORES[table][code][1]=static_cast<Score>(ordering);
        }
    }
    Evaluation::resetPolicyCross();
    Evaluation::installClassicalValueReadouts({});
    Evaluation::setScalingFactor(200.0f);
}
